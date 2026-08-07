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
    Works for all architectures: single_agent, supervisor_worker, peer_to_peer, debate_critic.
    """
    events = load_trace_events(trace_file)

    # 1. Generic metrics
    num_tool_calls = sum(1 for e in events if e.get("event_type") == "tool_call")
    num_llm_calls = sum(1 for e in events if e.get("event_type") == "llm_call")

    # Multi-agent architectures don't emit agent_finish at the top level —
    # they emit run_finish or supervisor_finish. Accept any of these as completion.
    has_finished = any(
        e.get("event_type") in ("agent_finish", "run_finish", "supervisor_finish", "revision_finish")
        for e in events
    )

    # 2. Coordination-specific metrics (architecture signal)
    #    These are zero for single_agent, non-zero only when the architecture uses them.
    num_delegations = sum(
        1 for e in events
        if e.get("event_type") == "tool_call"
        and e.get("payload", {}).get("role") == "supervisor_delegation"
    )
    num_workers_invoked = sum(1 for e in events if e.get("event_type") == "worker_start")
    num_handoffs = sum(1 for e in events if e.get("event_type") == "peer_handoff")
    num_critique_rounds = sum(1 for e in events if e.get("event_type") == "critic_review")
    num_revisions = sum(1 for e in events if e.get("event_type") == "revision_start")

    # 3. Tool error analysis
    tool_results = [e for e in events if e.get("event_type") == "tool_result"]
    failed_tool_results = [tr for tr in tool_results if tr.get("payload", {}).get("error") is True]

    unrecovered_tool_error = False
    for failed_tr in failed_tool_results:
        tool_name = failed_tr["payload"]["tool_name"]
        call_id = failed_tr["payload"]["tool_call_id"]
        call_event = next(
            (e for e in events if e.get("event_type") == "tool_call"
             and e["payload"].get("tool_call_id") == call_id), None
        )
        if not call_event:
            continue
        args = call_event["payload"].get("arguments", {})

        recovered = False
        failed_timestamp = failed_tr["timestamp"]
        for e in events:
            if e["timestamp"] > failed_timestamp:
                if e.get("event_type") == "tool_call" and e["payload"].get("tool_name") == tool_name:
                    if e["payload"].get("arguments") == args:
                        res_event = next(
                            (tr for tr in tool_results
                             if tr["timestamp"] > e["timestamp"]
                             and tr["payload"].get("tool_call_id") == e["payload"].get("tool_call_id")), None
                        )
                        if res_event and res_event["payload"].get("error") is False:
                            recovered = True
                            break
        if not recovered:
            unrecovered_tool_error = True
            break

    # 4. Database state check
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

    # 5. Trace semantic checks
    queried_profile = False
    searched_tickets = False
    updated_ticket = False

    for tr in tool_results:
        payload = tr.get("payload", {})
        if payload.get("error"):
            continue
        tool_name = payload.get("tool_name")
        res = payload.get("result", {})
        call_id = payload.get("tool_call_id")
        call_event = next(
            (e for e in events if e.get("event_type") == "tool_call"
             and e["payload"].get("tool_call_id") == call_id), None
        )
        args = call_event["payload"].get("arguments", {}) if call_event else {}

        if tool_name == "get_customer_profile" and args.get("customer_id") == "CUST-003":
            if isinstance(res, dict) and res.get("tier") == "enterprise":
                queried_profile = True
        elif tool_name == "search_tickets" and args.get("customer_id") == "CUST-003":
            if isinstance(res, dict):
                queried_profile_match = any(
                    t.get("customer_id") == "CUST-003" for t in res.get("tickets", [])
                )
                if queried_profile_match:
                    searched_tickets = True
        elif tool_name == "update_ticket" and args.get("status") == "escalated" and args.get("tier") == "enterprise":
            if isinstance(res, dict) and res.get("status") == "updated":
                updated_ticket = True

    # 6. Assemble full metrics dict (generic + coordination-specific)
    metrics = {
        # Generic
        "num_tool_calls": num_tool_calls,
        "num_llm_calls": num_llm_calls,
        "queried_profile": queried_profile,
        "searched_tickets": searched_tickets,
        "updated_ticket": updated_ticket,
        "db_status": db_status,
        "db_tier": db_tier,
        "db_correct": db_correct,
        # Coordination-specific (non-zero only for multi-agent architectures)
        "num_delegations": num_delegations,
        "num_workers_invoked": num_workers_invoked,
        "num_handoffs": num_handoffs,
        "num_critique_rounds": num_critique_rounds,
        "num_revisions": num_revisions,
    }

    # 7. Grading logic
    if not has_finished:
        return as_dict(GradeResult(
            passed=False,
            score=0.0,
            failure_category="incomplete",
            reason="Run did not complete (no agent_finish / run_finish / supervisor_finish event).",
            metrics=metrics
        ))

    if unrecovered_tool_error:
        return as_dict(GradeResult(
            passed=False,
            score=0.0,
            failure_category="tool_error_unrecovered",
            reason="Agent encountered an injected tool failure and failed to recover.",
            metrics=metrics
        ))

    if db_correct and queried_profile and updated_ticket:
        # Efficiency score: penalise extra LLM calls above architecture minimum.
        # Minimum varies: single=4, supervisor adds 1 per delegation, debate adds 2 per critique round.
        min_expected = 4 + (num_delegations * 1) + (num_critique_rounds * 2)
        efficiency_score = max(0.7, 1.0 - max(0, num_llm_calls - min_expected) * 0.05)
        return as_dict(GradeResult(
            passed=True,
            score=round(efficiency_score, 2),
            reason="Task completed successfully with correct final DB state and trace validation.",
            metrics=metrics
        ))
    else:
        missing = []
        if not queried_profile:
            missing.append("queried_profile")
        if not updated_ticket:
            missing.append("updated_ticket")
        if not db_correct:
            missing.append("correct_db_state")
        # Distinguish coordination failures from plain task failures:
        # coordination_failure = architecture machinery NEVER activated at all.
        # If any coordination event fired (delegation, handoff, critique, revision, worker),
        # the machinery ran — that's a task_failure, not a coordination_failure.
        coordination_miss = (
            num_delegations == 0 and num_workers_invoked == 0
            and num_handoffs == 0 and num_tool_calls == 0
            and num_critique_rounds == 0 and num_revisions == 0
        )
        category = "coordination_failure" if coordination_miss else "task_failure"
        reason = f"Task failed due to missing steps: {', '.join(missing)}."
        return as_dict(GradeResult(
            passed=False,
            score=0.0,
            failure_category=category,
            reason=reason,
            metrics=metrics
        ))


def as_dict(res: GradeResult) -> Dict[str, Any]:
    return asdict(res)
