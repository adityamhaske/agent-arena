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
    args = parser.parse_args()

    print(f"Agent Arena - Phase 1 Baseline Execution (Provider: {args.provider})")
    
    db_path = "eval_db.sqlite"
    setup_mock_db(db_path)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trace_filepath = f"trace_baseline_{timestamp}.jsonl"
    
    if args.provider == "anthropic":
        provider = AnthropicProvider(model_name="claude-sonnet-4-6")
    else:
        provider = GeminiProvider(model_name="gemini-1.5-pro")

    arch = SingleAgentArchitecture(
        provider=provider,
        trace_filepath=trace_filepath, 
        db_path=db_path,
        api_failure_rate=0.0,
        api_rate_limit_prob=0.3
    )
    
    print(f"Starting task execution...")
    print(f"Task Prompt: {TASK_PROMPT.strip()}")
    
    final_output = arch.run_task(TASK_PROMPT)
    
    print("\n--- Final Output ---")
    print(final_output)
    
    print(f"\nExecution finished. Trace logged to {trace_filepath}")
    
    try:
        from core.trace import TraceLogger
        root_events = TraceLogger.reconstruct_dag(trace_filepath)
        total_events = sum(1 for line in open(trace_filepath))
        print(f"Trace contains {total_events} events.")
    except Exception as e:
        print(f"Could not print trace summary: {e}")

if __name__ == "__main__":
    main()
