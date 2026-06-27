import os
import sqlite3
import argparse
from datetime import datetime

from core.architectures.single_agent import SingleAgentArchitecture
from evals.tasks.task_01_customer_escalation import TASK_PROMPT
from core.providers import AnthropicProvider, GeminiProvider

def setup_mock_db(db_path: str):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT,
            status TEXT,
            tier TEXT,
            description TEXT
        )
    ''')
    c.execute('DELETE FROM tickets')
    c.execute('INSERT INTO tickets (customer_id, description, status, tier) VALUES (?, ?, ?, ?)', 
              ('CUST-003', 'Server is down!', 'open', 'unknown'))
    conn.commit()
    conn.close()

def main():
    parser = argparse.ArgumentParser(description="Agent Arena - Phase 1 Baseline Execution")
    parser.add_argument("--provider", choices=["anthropic", "gemini"], default="gemini", help="Model provider to use")
    parser.add_argument("--model", type=str, default=None, help="Specific model name to use")
    parser.add_argument("--api-failure-rate", type=float, default=0.0, help="Failure rate of mock API (500 error)")
    parser.add_argument("--api-rate-limit-prob", type=float, default=0.3, help="Rate limit probability of mock API (429 error)")
    args = parser.parse_args()

    print(f"Agent Arena - Phase 1 Baseline Execution (Provider: {args.provider})")
    
    db_path = "eval_db.sqlite"
    setup_mock_db(db_path)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trace_filepath = f"trace_baseline_{timestamp}.jsonl"
    
    if args.provider == "anthropic":
        model_name = args.model or "claude-sonnet-4-6"
        provider = AnthropicProvider(model_name=model_name)
    else:
        model_name = args.model or "gemini-2.5-flash"
        provider = GeminiProvider(model_name=model_name)

    arch = SingleAgentArchitecture(
        provider=provider,
        trace_filepath=trace_filepath, 
        db_path=db_path,
        api_failure_rate=args.api_failure_rate,
        api_rate_limit_prob=args.api_rate_limit_prob
    )
    
    print(f"Starting task execution...")
    print(f"Task Prompt: {TASK_PROMPT.strip()}")
    
    final_output = arch.run_task(TASK_PROMPT)
    
    print("\n--- Final Output ---")
    print(final_output)
    
    print(f"\nExecution finished. Trace logged to {trace_filepath}")
    
    print("\n--- Grading Run ---")
    try:
        from evals.tasks.task_01_customer_escalation import grade_customer_escalation
        grade_res = grade_customer_escalation(trace_filepath, db_path)
        import json
        print(json.dumps(grade_res, indent=2))
    except Exception as e:
        print(f"Failed to grade run: {e}")

if __name__ == "__main__":
    main()
