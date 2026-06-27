# Tasks and Evaluations

Agent Arena evaluates architectures against two core tasks designed to expose different failure modes. Both tasks are verified by checking actual mock database state (`eval_db.sqlite`) and semantically scanning trace events for tool usage, rather than relying on LLM-as-a-judge grading.

## Task 01: Customer Escalation
**Tests:** Basic tool-use competence and single-agent logic.
**Prompt:** Look up the customer profile for 'CUST-003' using the CRM API. Find their open ticket in the ticketing system. Update the ticket with the customer's tier, and set the ticket status to 'escalated'.

**Success Criteria (`evals/tasks/task_01_customer_escalation.py`):**
1. `queried_profile`: The agent successfully called `get_customer_profile` and retrieved `tier = enterprise`.
2. `updated_ticket`: The agent successfully called `update_ticket` setting status to `escalated` and tier to `enterprise`.
3. `db_correct`: The underlying SQLite database confirms that `CUST-003`'s ticket is `escalated` and `enterprise`.

*Note: All architectures pass this easily. Failures here generally represent general LLM hallucination or logic errors (e.g., hallucinating a successful tool call without making it).*

## Task 02: Credit Hold Escalation (The "Trap" Task)
**Tests:** Information-asymmetry survival across coordination boundaries.
**Prompt:** Look up the account status for customer 'CUST-004'. Find their open support ticket. Apply the following escalation policy: If the customer has a credit hold on their account, set the ticket status to 'on_hold' and append '[CREDIT_HOLD]' to the ticket description. Otherwise, set the ticket status to 'escalated' and set the tier to match the customer's account tier.

**Success Criteria (`evals/tasks/task_02_credit_hold_escalation.py`):**
1. The CRM profile query for `CUST-004` returns `credit_hold=True`. 
2. The agent making the final decision must have access to `credit_hold`.
   - `peer_to_peer`: Must be present in the `peer_handoff` message.
   - `supervisor_worker`: Must be present in the CRM worker's natural language `worker_finish` summary.
3. `db_correct`: The underlying SQLite database confirms the ticket is `on_hold` with `[CREDIT_HOLD]` in the description.

*Note: This task is explicitly designed to trap architectures with lossy boundaries. If the field is dropped during a handoff, the agent will confidently escalate the ticket, causing a definitive coordination failure.*
