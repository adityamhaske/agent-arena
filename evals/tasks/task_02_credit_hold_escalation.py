import sqlite3
from typing import Dict, Any, Optional
from dataclasses import asdict
from evals.grader import GradeResult, load_trace_events

TASK_PROMPT = """
Look up the account status for customer 'CUST-004' using the CRM API.
Find their open support ticket in the ticketing system.

Apply the following escalation policy:
- If the customer has a credit hold on their account, set the ticket status
  to 'on_hold' and append '[CREDIT_HOLD]' to the ticket description.
- Otherwise, set the ticket status to 'escalated' and set the tier to match
  the customer's account tier.
"""


def grade_credit_hold_escalation(trace_file: str, db_path: str) -> Dict[str, Any]:
    """
    Evaluates the credit-hold escalation run (task_02).

    The key information asymmetry under test:
      - CUST-004 has credit_hold=True in the CRM API response.
      - The correct action is status='on_hold' + '[CREDIT_HOLD]' in description.
      - Multi-agent architectures with restricted handoff/delegation may drop
        the credit_hold field, causing a confident-but-wrong escalation.
    """
    events = load_trace_events(trace_file)

    # 1. Generic metrics
    num_tool_calls = sum(1 for e in events if e.get("event_type") == "tool_call")
    num_llm_calls = sum(1 for e in events if e.get("event_type") == "llm_call")

    has_finished = any(
        e.get("event_type") in (
            "agent_finish", "run_finish", "supervisor_finish", "revision_finish"
        )
        for e in events
    )

    # 2. Coordination-specific metrics (same set as task_01)
    num_delegations = sum(
        1 for e in events
        if e.get("event_type") == "tool_call"
        and e.get("payload", {}).get("role") == "supervisor_delegation"
    )
    num_workers_invoked = sum(1 for e in events if e.get("event_type") == "worker_start")
    num_handoffs = sum(1 for e in events if e.get("event_type") == "peer_handoff")
    num_critique_rounds = sum(1 for e in events if e.get("event_type") == "critic_review")
    num_revisions = sum(1 for e in events if e.get("event_type") == "revision_start")

    # 3. Key semantic checks
    tool_results = [e for e in events if e.get("event_type") == "tool_result"]

    # credit_hold_seen_in_crm_result: the get_customer_profile tool result contains credit_hold=True.
    # This is True for ALL architectures if the CRM tool was called, even if the receiving
    # agent in a multi-agent pipeline never saw the value.
    credit_hold_seen_in_crm_result = False

    # credit_hold_in_handoff: for peer_to_peer — did the HANDOFF MESSAGE text contain "credit_hold"?
    # If False but credit_hold_seen_in_crm_result is True → boundary drop confirmed.
    credit_hold_in_handoff = False

    # credit_hold_in_worker_summary: for supervisor_worker — did any worker_finish result text mention credit_hold?
    # If True → the CRM Worker passed the info to the supervisor; supervisor had the data.
    credit_hold_in_worker_summary = False

    applied_hold_policy = False
    applied_escalation_wrongly = False
    description_updated = False

    for tr in tool_results:
        payload = tr.get("payload", {})
        if payload.get("error"):
            continue
        tool_name = payload.get("tool_name")
        res = payload.get("result", {})

        call_id = payload.get("tool_call_id")
        call_event = next(
            (e for e in events
             if e.get("event_type") == "tool_call"
             and e["payload"].get("tool_call_id") == call_id), None
        )
        args = call_event["payload"].get("arguments", {}) if call_event else {}

        if tool_name == "get_customer_profile" and args.get("customer_id") == "CUST-004":
            if isinstance(res, dict) and res.get("credit_hold") is True:
                credit_hold_seen_in_crm_result = True

        elif tool_name == "update_ticket":
            status_set = args.get("status", "")
            if status_set == "on_hold" and isinstance(res, dict) and res.get("status") == "updated":
                applied_hold_policy = True
            elif status_set == "escalated":
                applied_escalation_wrongly = True
            desc_arg = str(args.get("description", ""))
            if "[CREDIT_HOLD]" in desc_arg:
                description_updated = True

        elif tool_name == "create_ticket":
            status_set = args.get("status", "")
            if status_set == "on_hold":
                applied_hold_policy = True
            desc_arg = str(args.get("description", ""))
            if "[CREDIT_HOLD]" in desc_arg:
                description_updated = True

    # Check cross-boundary payloads for coordination-specific signal
    for e in events:
        if e.get("event_type") == "peer_handoff":
            msg = str(e["payload"].get("handoff_message", ""))
            if "credit_hold" in msg.lower():
                credit_hold_in_handoff = True

        if e.get("event_type") == "worker_finish":
            result_text = str(e["payload"].get("result", ""))
            if "credit_hold" in result_text.lower() or "credit hold" in result_text.lower():
                credit_hold_in_worker_summary = True

    # Unified flag: did the agent making the FINAL decision have access to credit_hold?
    # For single_agent and debate_critic: yes iff credit_hold_seen_in_crm_result.
    # For peer_to_peer: only if credit_hold_in_handoff (Agent B's only source).
    # For supervisor_worker: only if credit_hold_in_worker_summary (supervisor's source).
    any_coordination = (
        num_workers_invoked > 0 or num_handoffs > 0
        or num_critique_rounds > 0 or num_delegations > 0
    )
    if not any_coordination:
        # Single-agent or debate_critic (proposer has all tools)
        decision_agent_saw_credit_hold = credit_hold_seen_in_crm_result
    elif num_handoffs > 0:
        # peer_to_peer: Agent B's only source is the handoff message
        decision_agent_saw_credit_hold = credit_hold_in_handoff
    elif num_workers_invoked > 0:
        # supervisor_worker: supervisor's source is the worker_finish text
        decision_agent_saw_credit_hold = credit_hold_in_worker_summary
    else:
        decision_agent_saw_credit_hold = credit_hold_seen_in_crm_result


    # 4. DB state check
    db_correct = False
    db_status = None
    db_description = None

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tickets WHERE customer_id = 'CUST-004'")
        row = c.fetchone()
        if row:
            db_status = row["status"]
            db_description = row["description"] or ""
            if db_status == "on_hold" and "[CREDIT_HOLD]" in db_description:
                db_correct = True
        conn.close()
    except Exception as e:
        return as_dict(GradeResult(
            passed=False,
            score=0.0,
            failure_category="task_failure",
            reason=f"Database check failed: {str(e)}",
            metrics={"num_tool_calls": num_tool_calls, "num_llm_calls": num_llm_calls}
        ))

    # 5. Assemble metrics
    metrics = {
        # Generic
        "num_tool_calls": num_tool_calls,
        "num_llm_calls": num_llm_calls,
        "db_status": db_status,
        "db_description": db_description,
        "db_correct": db_correct,
        # Task-02-specific semantic flags
        "credit_hold_seen_in_crm_result": credit_hold_seen_in_crm_result,
        "credit_hold_in_handoff": credit_hold_in_handoff,
        "credit_hold_in_worker_summary": credit_hold_in_worker_summary,
        "decision_agent_saw_credit_hold": decision_agent_saw_credit_hold,
        "applied_hold_policy": applied_hold_policy,
        "applied_escalation_wrongly": applied_escalation_wrongly,
        "description_updated": description_updated,
        # Coordination-specific
        "num_delegations": num_delegations,
        "num_workers_invoked": num_workers_invoked,
        "num_handoffs": num_handoffs,
        "num_critique_rounds": num_critique_rounds,
        "num_revisions": num_revisions,
    }

    # 6. Grading logic
    if not has_finished:
        return as_dict(GradeResult(
            passed=False,
            score=0.0,
            failure_category="incomplete",
            reason="Run did not complete (no finish event in trace).",
            metrics=metrics
        ))

    if db_correct:
        # Efficiency score: fewer LLM calls = better.
        min_expected = 4 + (num_delegations * 1) + (num_critique_rounds * 2)
        efficiency = max(0.7, 1.0 - max(0, num_llm_calls - min_expected) * 0.05)
        return as_dict(GradeResult(
            passed=True,
            score=round(efficiency, 2),
            reason=(
                "Task completed correctly: status=on_hold and [CREDIT_HOLD] "
                "appended to description."
            ),
            metrics=metrics
        ))

    # Failure — determine category
    if not decision_agent_saw_credit_hold:
        # The agent responsible for the final ticketing action never had access to credit_hold.
        # For peer_to_peer: credit_hold was not in the handoff message.
        # For supervisor_worker: credit_hold was not in the CRM worker's summary.
        # This is a coordination_failure: the architecture boundary caused information loss.
        category = "coordination_failure" if any_coordination else "task_failure"
        reason = (
            "The decision-making agent did not have access to credit_hold=True "
            + ("— field dropped at handoff/delegation boundary (coordination_failure)."
               if any_coordination
               else "— agent failed to read the customer profile.")
        )
    elif applied_escalation_wrongly:
        # Decision agent SAW credit_hold=True but escalated anyway — pure reasoning failure
        reason = (
            "Decision agent saw credit_hold=True but called update_ticket(status=escalated). "
            "Credit hold policy was ignored (task_failure, not coordination_failure)."
        )
        category = "task_failure"
    else:
        # Correct status but description missing, or other partial completion
        missing = []
        if db_status != "on_hold":
            missing.append(f"db_status={db_status!r} (want 'on_hold')")
        if "[CREDIT_HOLD]" not in (db_description or ""):
            missing.append("'[CREDIT_HOLD]' missing from description")
        reason = f"Incorrect final state: {', '.join(missing)}."
        category = "task_failure"

    return as_dict(GradeResult(
        passed=False,
        score=0.0,
        failure_category=category,
        reason=reason,
        metrics=metrics
    ))



def as_dict(res: GradeResult) -> Dict[str, Any]:
    return asdict(res)
