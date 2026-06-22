# Task Definition: Customer Escalation

TASK_PROMPT = """
Look up the customer profile for 'CUST-003' using the CRM API.
Find their open ticket in the ticketing system.
Update the ticket with the customer's tier, and set the ticket status to 'escalated'.
"""

def grader_stub(trace_file: str, db_path: str) -> dict:
    """
    Phase 2 Grader Function Stub.
    
    This function will be implemented in Phase 2 to evaluate the run.
    It should verify:
    1. The agent queried the Mock API for CUST-003 and got tier 'enterprise'.
    2. The agent found the existing ticket for CUST-003.
    3. The agent updated the ticket correctly (status = 'escalated', tier = 'enterprise').
    4. Evaluates efficiency (how many tool calls, did it recover from injected failures correctly?).
    
    Args:
        trace_file: Path to the generated trace JSONL file for reconstructing the DAG.
        db_path: Path to the SQLite DB to assert final state.
        
    Returns:
        A dictionary with grading results: {'score': 1.0, 'passed': True, 'reason': '...'}
    """
    pass
