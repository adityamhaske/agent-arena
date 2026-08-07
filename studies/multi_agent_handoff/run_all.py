#!/usr/bin/env python3
"""
run_all.py — Full sweep runner for Agent Arena.

Runs the architecture × task × provider × trial matrix, with optional
per-cell trial count overrides. Saves a structured results manifest to
results/sweep_<timestamp>.json for use by report_generator.py.

Usage examples:
  # Full 48-run sweep (4 arch × 2 tasks × 2 providers × 3 trials)
  python run_all.py

  # Gemini only, bump supervisor_worker×task_02 trials
  python run_all.py --providers gemini --sw-task02-trials 7

  # Quick smoke test: 1 trial each, gemini only
  python run_all.py --providers gemini --trials 1
"""
import os
import json
import time
import sqlite3
import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ARCHITECTURES = ["single_agent", "peer_to_peer", "supervisor_worker", "debate_critic"]
TASKS = ["task_01", "task_02"]
PROVIDERS = {
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-5",
}
INTER_RUN_SLEEP = 25  # seconds between runs — conservative for paid Gemini tier


def get_api_key(provider: str) -> str:
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise EnvironmentError("GEMINI_API_KEY not set")
        return key
    elif provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY not set. "
                "Set it or exclude anthropic with --providers gemini"
            )
        return key
    raise ValueError(f"Unknown provider: {provider}")


def run_single(
    architecture: str,
    task: str,
    provider: str,
    model: str,
    trial: int,
    env: dict,
    trace_dir: str,
) -> dict:
    """Run one trial and return a result record."""
    cmd = [
        "python", "run_baseline.py",
        "--architecture", architecture,
        "--task", task,
        "--provider", provider,
        "--model", model,
        "--api-failure-rate", "0.0",
        "--trace-dir", trace_dir,
    ]
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, **env},
        )
        stdout = result.stdout
        stderr = result.stderr
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        stdout = ""
        stderr = "subprocess timed out after 300s"
        success = False

    # Extract trace filepath and grade result from stdout
    trace_file = None
    grade = None
    for line in stdout.splitlines():
        if line.startswith("Trace logged to:"):
            trace_file = line.split(":", 1)[1].strip()
        # Grade result is the JSON block after "--- Grading Run ---"

    # Parse the grade JSON block
    lines = stdout.splitlines()
    in_grade = False
    grade_lines = []
    for line in lines:
        if "--- Grading Run ---" in line:
            in_grade = True
            continue
        if in_grade:
            grade_lines.append(line)
    if grade_lines:
        try:
            grade = json.loads("\n".join(grade_lines))
        except json.JSONDecodeError:
            grade = None

    return {
        "architecture": architecture,
        "task": task,
        "provider": provider,
        "model": model,
        "trial": trial,
        "started_at": started_at,
        "success": success,
        "trace_file": trace_file,
        "grade": grade,
        "stderr_snippet": stderr[:500] if stderr else "",
    }


def main():
    parser = argparse.ArgumentParser(description="Agent Arena — Full Sweep Runner")
    parser.add_argument(
        "--architectures", nargs="+",
        default=ARCHITECTURES,
        choices=ARCHITECTURES,
        help="Architectures to run (default: all)",
    )
    parser.add_argument(
        "--tasks", nargs="+",
        default=TASKS,
        choices=TASKS,
        help="Tasks to run (default: both)",
    )
    parser.add_argument(
        "--providers", nargs="+",
        default=list(PROVIDERS.keys()),
        choices=list(PROVIDERS.keys()),
        help="Providers to run (default: gemini anthropic)",
    )
    parser.add_argument(
        "--trials", type=int, default=3,
        help="Number of trials per cell (default: 3)",
    )
    parser.add_argument(
        "--sw-task02-trials", type=int, default=None,
        help="Override trial count for supervisor_worker×task_02 (default: same as --trials)",
    )
    parser.add_argument(
        "--sleep", type=int, default=INTER_RUN_SLEEP,
        help=f"Seconds to sleep between runs (default: {INTER_RUN_SLEEP})",
    )
    parser.add_argument(
        "--output-dir", default="results",
        help="Directory to write sweep manifest (default: results/)",
    )
    args = parser.parse_args()

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sweep_date = datetime.now().strftime("%Y%m%d")
    trace_dir = str(Path(args.output_dir) / f"sweep_{sweep_date}")
    Path(trace_dir).mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.output_dir) / f"sweep_{timestamp}.json"

    # Build the run list
    runs = []
    for provider in args.providers:
        for arch in args.architectures:
            for task in args.tasks:
                if (
                    arch == "supervisor_worker"
                    and task == "task_02"
                    and args.sw_task02_trials is not None
                ):
                    n_trials = args.sw_task02_trials
                else:
                    n_trials = args.trials
                for trial in range(1, n_trials + 1):
                    runs.append((arch, task, provider, trial))

    total = len(runs)
    print(f"\nAgent Arena — Full Sweep")
    print(f"  Runs planned : {total}")
    print(f"  Architectures: {args.architectures}")
    print(f"  Tasks        : {args.tasks}")
    print(f"  Providers    : {args.providers}")
    print(f"  Trials       : {args.trials} (sw×task_02: {args.sw_task02_trials or args.trials})")
    print(f"  Output       : {manifest_path}")
    print(f"  Est. time    : {total * (args.sleep + 30) // 60} min\n")

    results = []
    for i, (arch, task, provider, trial) in enumerate(runs, 1):
        model = PROVIDERS[provider]
        print(f"[{i:>3}/{total}] {arch} × {task} × {provider} × trial {trial} ...", end=" ", flush=True)

        try:
            api_key = get_api_key(provider)
        except EnvironmentError as e:
            print(f"SKIP — {e}")
            results.append({
                "architecture": arch, "task": task, "provider": provider,
                "model": model, "trial": trial,
                "success": False, "grade": None,
                "trace_file": None,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "stderr_snippet": str(e),
                "skipped": True,
            })
            continue

        env = {
            "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        }
        if provider == "gemini":
            env["GEMINI_API_KEY"] = api_key
        else:
            env["ANTHROPIC_API_KEY"] = api_key

        rec = run_single(arch, task, provider, model, trial, env, trace_dir)
        results.append(rec)

        grade = rec.get("grade") or {}
        passed = grade.get("passed")
        fc = grade.get("failure_category", "?")
        score = grade.get("score", "?")

        if passed is True:
            print(f"PASS  score={score}")
        elif passed is False:
            print(f"FAIL  [{fc}]")
        else:
            print(f"ERROR (no grade)")

        # Save manifest after every run (safe against crashes)
        with open(manifest_path, "w") as f:
            json.dump({"sweep_timestamp": timestamp, "runs": results}, f, indent=2)

        if i < total:
            time.sleep(args.sleep)

    # Final summary
    passed_count = sum(1 for r in results if (r.get("grade") or {}).get("passed") is True)
    failed_count = sum(1 for r in results if (r.get("grade") or {}).get("passed") is False
                       and (r.get("grade") or {}).get("failure_category") != "incomplete")
    incomplete_count = sum(1 for r in results if (r.get("grade") or {}).get("failure_category") == "incomplete")
    skipped_count = sum(1 for r in results if r.get("skipped"))

    print(f"\n{'='*60}")
    print(f"Sweep complete — {manifest_path}")
    print(f"  Passed    : {passed_count}/{total}")
    print(f"  Failed    : {failed_count}/{total}")
    print(f"  Incomplete: {incomplete_count}/{total}  (quota/crash — excluded from pass rate)")
    print(f"  Skipped   : {skipped_count}/{total}  (missing API key)")
    print(f"  Adjusted pass rate (excl. incomplete+skipped): "
          f"{passed_count}/{total - incomplete_count - skipped_count} = "
          f"{passed_count / max(1, total - incomplete_count - skipped_count):.0%}")
    print(f"\nRun: python report_generator.py {manifest_path}")


if __name__ == "__main__":
    main()
