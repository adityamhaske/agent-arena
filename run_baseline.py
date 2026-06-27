import os
import json
import sqlite3
import argparse
from datetime import datetime

from core.architectures import (
    SingleAgentArchitecture,
    SupervisorWorkerArchitecture,
    PeerToPeerArchitecture,
    DebateCriticArchitecture,
)
from core.providers import AnthropicProvider, GeminiProvider

ARCHITECTURE_MAP = {
    "single_agent": SingleAgentArchitecture,
    "supervisor_worker": SupervisorWorkerArchitecture,
    "peer_to_peer": PeerToPeerArchitecture,
    "debate_critic": DebateCriticArchitecture,
}

# Task registry: task_id -> (prompt, grader_fn, db_seeder_fn)
def _seed_task_01(db_path: str):
    """Seed CUST-003 open ticket for task_01."""
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
    c.execute(
        'INSERT INTO tickets (customer_id, description, status, tier) VALUES (?, ?, ?, ?)',
        ('CUST-003', 'Server is down!', 'open', 'unknown')
    )
    conn.commit()
    conn.close()

def _seed_task_02(db_path: str):
    """Seed CUST-004 open ticket for task_02 (credit hold trap)."""
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
    c.execute(
        'INSERT INTO tickets (customer_id, description, status, tier) VALUES (?, ?, ?, ?)',
        ('CUST-004', 'Service degraded', 'open', 'unknown')
    )
    conn.commit()
    conn.close()

def _get_task(task_id: str):
    if task_id == "task_01":
        from evals.tasks.task_01_customer_escalation import (
            TASK_PROMPT, grade_customer_escalation,
        )
        return TASK_PROMPT, grade_customer_escalation, _seed_task_01
    elif task_id == "task_02":
        from evals.tasks.task_02_credit_hold_escalation import (
            TASK_PROMPT, grade_credit_hold_escalation,
        )
        return TASK_PROMPT, grade_credit_hold_escalation, _seed_task_02
    else:
        raise ValueError(f"Unknown task: {task_id!r}")


def main():
    parser = argparse.ArgumentParser(description="Agent Arena — Baseline Execution")
    parser.add_argument(
        "--provider", choices=["anthropic", "gemini"], default="gemini",
        help="Model provider to use",
    )
    parser.add_argument("--model", type=str, default=None, help="Specific model name")
    parser.add_argument(
        "--architecture",
        choices=list(ARCHITECTURE_MAP.keys()),
        default="single_agent",
        help="Agent architecture to run",
    )
    parser.add_argument(
        "--task",
        choices=["task_01", "task_02"],
        default="task_01",
        help="Evaluation task to run (task_01: customer escalation, task_02: credit hold trap)",
    )
    parser.add_argument(
        "--api-failure-rate", type=float, default=0.0,
        help="Failure rate of mock API (500 error)",
    )
    parser.add_argument(
        "--api-rate-limit-prob", type=float, default=0.0,
        help="Rate limit probability of mock API (429 error)",
    )
    args = parser.parse_args()

    task_prompt, grader_fn, seed_fn = _get_task(args.task)

    print(f"Agent Arena — Architecture: {args.architecture} | Provider: {args.provider} | Task: {args.task}")

    db_path = "eval_db.sqlite"
    seed_fn(db_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trace_filepath = f"trace_{args.architecture}_{args.provider}_{args.task}_{timestamp}.jsonl"

    if args.provider == "anthropic":
        model_name = args.model or "claude-sonnet-4-6"
        provider = AnthropicProvider(model_name=model_name)
    else:
        model_name = args.model or "gemini-2.5-flash"
        provider = GeminiProvider(model_name=model_name)

    ArchClass = ARCHITECTURE_MAP[args.architecture]
    arch = ArchClass(
        provider=provider,
        trace_filepath=trace_filepath,
        db_path=db_path,
        api_failure_rate=args.api_failure_rate,
        api_rate_limit_prob=args.api_rate_limit_prob,
    )

    print(f"Task Prompt: {task_prompt.strip()}\n")

    final_output = arch.run_task(task_prompt)

    print("\n--- Final Output ---")
    print(final_output)

    print(f"\nTrace logged to: {trace_filepath}")

    print("\n--- Grading Run ---")
    try:
        grade_res = grader_fn(trace_filepath, db_path)
        print(json.dumps(grade_res, indent=2))
    except Exception as e:
        import traceback
        print(f"Failed to grade run: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
