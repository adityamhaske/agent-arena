import sqlite3
from typing import Dict, Any, Optional
from dataclasses import asdict
from evals.grader import GradeResult, load_trace_events

TASK_PROMPT = """
Look up the customer profile for 'CUST-003' using the CRM API.
Find their open ticket in the ticketing system.
Update the ticket with the customer's tier, and set the ticket status to 'escalated'.
"""

def grade_customer_escalation(trace_file: str, db_path: str) -> Dict[str, Any]:
    """
    Evaluates the customer escalation run.
    Verifies database state and traces to output a GradeResult.
    """
    events = load_trace_events(trace_file)
    
    # 1. Gather metrics
    num_tool_calls = sum(1 for e in events if e.get("event_type") == "tool_call")
    num_llm_calls = sum(1 for e in events if e.get("event_type") == "llm_call")
    has_finished = any(e.get("event_type") == "agent_finish" for e in events)
    
    # Detect tool errors
    tool_results = [e for e in events if e.get("event_type") == "tool_result"]
    failed_tool_results = [tr for tr in tool_results if tr.get("payload", {}).get("error") is True]
    
    # Check if failed tool calls were eventually recovered (succeeded later)
    unrecovered_tool_error = False
    for failed_tr in failed_tool_results:
        tool_name = failed_tr["payload"]["tool_name"]
        call_id = failed_tr["payload"]["tool_call_id"]
        # Find the original tool call payload
        call_event = next((e for e in events if e.get("event_type") == "tool_call" and e["payload"].get("tool_call_id") == call_id), None)
        if not call_event:
            continue
        args = call_event["payload"].get("arguments", {})
        
        # Check if there is a later successful tool call of the same tool name with the same arguments
        recovered = False
        failed_timestamp = failed_tr["timestamp"]
        for e in events:
            if e["timestamp"] > failed_timestamp:
                if e.get("event_type") == "tool_call" and e["payload"].get("tool_name") == tool_name:
                    if e["payload"].get("arguments") == args:
                        # Find the corresponding tool_result
                        res_event = next((tr for tr in tool_results if tr["timestamp"] > e["timestamp"] and tr["payload"].get("tool_call_id") == e["payload"].get("tool_call_id")), None)
                        if res_event and res_event["payload"].get("error") is False:
                            recovered = True
                            break
        if not recovered:
            unrecovered_tool_error = True
            break

    # 2. Check Database State
    db_correct = False
    db_status = None
    db_tier = None
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tickets WHERE customer_id = 'CUST-003'")
        row = c.fetchone()
        if row:
            db_status = row["status"]
            db_tier = row["tier"]
            if db_status == "escalated" and db_tier == "enterprise":
                db_correct = True
        conn.close()
    except Exception as e:
        return as_dict(GradeResult(
            passed=False,
            score=0.0,
            failure_category="task_failure",
            reason=f"Database check failed with exception: {str(e)}",
            metrics={"num_tool_calls": num_tool_calls, "num_llm_calls": num_llm_calls}
        ))

    # 3. Check Trace Semantics (did it actually query profile, etc. or hallucinate?)
    queried_profile = False
    searched_tickets = False
    updated_ticket = False
    
    for tr in tool_results:
        payload = tr.get("payload", {})
        if payload.get("error"):
            continue
        tool_name = payload.get("tool_name")
        res = payload.get("result", {})
        
        # We need to trace back to check the tool call arguments
        call_id = payload.get("tool_call_id")
        call_event = next((e for e in events if e.get("event_type") == "tool_call" and e["payload"].get("tool_call_id") == call_id), None)
        args = call_event["payload"].get("arguments", {}) if call_event else {}
        
        if tool_name == "get_customer_profile" and args.get("customer_id") == "CUST-003":
            if res.get("tier") == "enterprise":
                queried_profile = True
        elif tool_name == "search_tickets" and args.get("customer_id") == "CUST-003":
            queried_profile_match = any(t.get("customer_id") == "CUST-003" for t in res.get("tickets", []))
            if queried_profile_match:
                searched_tickets = True
        elif tool_name == "update_ticket" and args.get("status") == "escalated" and args.get("tier") == "enterprise":
            if res.get("status") == "updated":
                updated_ticket = True

    # 4. Grading Logic and Failure Categorization
    metrics = {
        "num_tool_calls": num_tool_calls,
        "num_llm_calls": num_llm_calls,
        "queried_profile": queried_profile,
        "searched_tickets": searched_tickets,
        "updated_ticket": updated_ticket,
        "db_status": db_status,
        "db_tier": db_tier,
        "db_correct": db_correct
    }

    if not has_finished:
        return as_dict(GradeResult(
            passed=False,
            score=0.0,
            failure_category="incomplete",
            reason="Agent run did not complete (no agent_finish event).",
            metrics=metrics
        ))
        
    if unrecovered_tool_error:
        return as_dict(GradeResult(
            passed=False,
            score=0.0,
            failure_category="tool_error_unrecovered",
            reason="Agent encountered an injected tool failure and failed to recover/retry.",
            metrics=metrics
        ))

    # All semantics & DB checks must pass
    if db_correct and queried_profile and updated_ticket:
        # Calculate efficiency score (shorter is better)
        # Optimal: 1 llm_call to query profile, 1 to search tickets, 1 to update ticket, 1 to finish = 4 llm calls.
        # Max iterations is 15. We scale score between 0.7 and 1.0 based on call count.
        efficiency_score = max(0.7, 1.0 - (num_llm_calls - 4) * 0.05)
        return as_dict(GradeResult(
            passed=True,
            score=round(efficiency_score, 2),
            reason="Task completed successfully with correct final DB state and trace validation.",
            metrics=metrics
        ))
    else:
        # Failure classification
        missing = []
        if not queried_profile:
            missing.append("queried_profile")
        if not updated_ticket:
            missing.append("updated_ticket")
        if not db_correct:
            missing.append("correct_db_state")
            
        reason = f"Task failed due to missing verification steps: {', '.join(missing)}."
        return as_dict(GradeResult(
            passed=False,
            score=0.0,
            failure_category="task_failure",
            reason=reason,
            metrics=metrics
        ))

def as_dict(res: GradeResult) -> Dict[str, Any]:
    return asdict(res)
