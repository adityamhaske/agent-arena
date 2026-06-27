#!/usr/bin/env python3
"""
report_generator.py — Produces a Markdown analysis report from a sweep manifest.

Pass rate handling (per user requirement):
  - 'incomplete' runs (quota exhaustion, crash) are EXCLUDED from the denominator.
  - Both raw_pass_rate (incompletes as failures) and adjusted_pass_rate are reported.
  - 'skipped' runs (missing API key) are excluded from all calculations.

Usage:
  python report_generator.py results/sweep_<timestamp>.json
  python report_generator.py results/sweep_<timestamp>.json --output results/report.md
"""
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict


def load_manifest(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def classify(run: dict) -> str:
    """Return 'pass', 'fail', 'incomplete', or 'skipped'."""
    if run.get("skipped"):
        return "skipped"
    grade = run.get("grade") or {}
    fc = grade.get("failure_category", "")
    if grade.get("passed") is True:
        return "pass"
    if fc == "incomplete":
        return "incomplete"
    return "fail"


def pass_rates(runs: list) -> dict:
    """
    Compute pass rate stats for a list of runs.
    - Skipped runs are excluded from everything.
    - Incomplete runs are excluded from the adjusted denominator.
    """
    active = [r for r in runs if not r.get("skipped")]
    if not active:
        return {"n": 0, "passed": 0, "failed": 0, "incomplete": 0,
                "raw_pass_rate": None, "adjusted_pass_rate": None,
                "completion_rate": None}

    passed = sum(1 for r in active if classify(r) == "pass")
    failed = sum(1 for r in active if classify(r) == "fail")
    incomplete = sum(1 for r in active if classify(r) == "incomplete")

    n = len(active)
    adjusted_n = n - incomplete
    return {
        "n": n,
        "passed": passed,
        "failed": failed,
        "incomplete": incomplete,
        "raw_pass_rate": passed / n if n else None,
        "adjusted_pass_rate": passed / adjusted_n if adjusted_n else None,
        "completion_rate": (n - incomplete) / n if n else None,
    }


def mean_metric(runs: list, key: str, sub: str = None) -> str:
    """Mean of a metric over passing runs. key=top-level or 'metrics.sub'."""
    vals = []
    for r in runs:
        if classify(r) != "pass":
            continue
        grade = r.get("grade") or {}
        if sub:
            v = (grade.get("metrics") or {}).get(sub)
        else:
            v = grade.get(key)
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if not vals:
        return "—"
    return f"{sum(vals)/len(vals):.2f}"


def fmt_rate(v) -> str:
    if v is None:
        return "—"
    return f"{v:.0%}"


def generate_report(manifest: dict) -> str:
    runs = manifest["runs"]
    ts = manifest.get("sweep_timestamp", "unknown")
    active = [r for r in runs if not r.get("skipped")]

    # Group by (architecture, task, provider)
    cells: dict = defaultdict(list)
    for r in active:
        cells[(r["architecture"], r["task"], r["provider"])].append(r)

    architectures = sorted({r["architecture"] for r in active})
    tasks = sorted({r["task"] for r in active})
    providers = sorted({r["provider"] for r in active})

    lines = []
    lines.append(f"# Agent Arena — Sweep Report")
    lines.append(f"")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    lines.append(f"**Sweep timestamp:** `{ts}`  ")
    lines.append(f"**Total runs:** {len(active)} active ({len(runs) - len(active)} skipped/missing key)  ")
    lines.append(f"")

    # ── Section 1: Quota / Completion health ──────────────────────────────
    lines.append(f"## 1. Completion Health")
    lines.append(f"")
    lines.append(f"> `incomplete` = quota exhaustion or crash before a finish event.")
    lines.append(f"> These are excluded from adjusted pass rates but reported as real signal.")
    lines.append(f"")

    stats = pass_rates(active)
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Total active runs | {stats['n']} |")
    lines.append(f"| Passed | {stats['passed']} |")
    lines.append(f"| Failed | {stats['failed']} |")
    lines.append(f"| Incomplete (quota/crash) | {stats['incomplete']} |")
    lines.append(f"| Completion rate | {fmt_rate(stats['completion_rate'])} |")
    lines.append(f"| Raw pass rate | {fmt_rate(stats['raw_pass_rate'])} |")
    lines.append(f"| **Adjusted pass rate** (excl. incomplete) | **{fmt_rate(stats['adjusted_pass_rate'])}** |")
    lines.append(f"")

    # ── Section 2: Pass rates by architecture × task ──────────────────────
    lines.append(f"## 2. Pass Rate by Architecture × Task")
    lines.append(f"")
    lines.append(f"> Format: `adj_pass_rate` (n trials, n incomplete excluded).  ")
    lines.append(f"> Raw pass rate shown in parentheses where they differ.")
    lines.append(f"")

    for task in tasks:
        lines.append(f"### {task}")
        lines.append(f"")
        header = "| Architecture |" + "".join(f" {p} |" for p in providers)
        lines.append(header)
        lines.append("|---|" + "---|" * len(providers))
        for arch in architectures:
            row = f"| {arch} |"
            for provider in providers:
                cell_runs = cells[(arch, task, provider)]
                if not cell_runs:
                    row += " — |"
                    continue
                s = pass_rates(cell_runs)
                adj = fmt_rate(s["adjusted_pass_rate"])
                raw = fmt_rate(s["raw_pass_rate"])
                n = s["n"]
                inc = s["incomplete"]
                note = f" (raw {raw})" if s["raw_pass_rate"] != s["adjusted_pass_rate"] else ""
                inc_note = f", {inc} incomplete" if inc else ""
                row += f" {adj}{note} (n={n}{inc_note}) |"
            lines.append(row)
        lines.append(f"")

    # ── Section 3: Failure category breakdown ─────────────────────────────
    lines.append(f"## 3. Failure Category Breakdown")
    lines.append(f"")
    lines.append(f"> Categories: `task_failure` · `coordination_failure` · `tool_error_unrecovered` · `incomplete`")
    lines.append(f"")

    for task in tasks:
        lines.append(f"### {task}")
        lines.append(f"")
        lines.append(f"| Architecture | Provider | pass | task_failure | coordination_failure | tool_error_unrecovered | incomplete |")
        lines.append(f"|---|---|---|---|---|---|---|")
        for arch in architectures:
            for provider in providers:
                cell_runs = cells[(arch, task, provider)]
                if not cell_runs:
                    continue
                counts = defaultdict(int)
                for r in cell_runs:
                    grade = r.get("grade") or {}
                    if grade.get("passed"):
                        counts["pass"] += 1
                    else:
                        fc = grade.get("failure_category") or "unknown"
                        counts[fc] += 1
                lines.append(
                    f"| {arch} | {provider} "
                    f"| {counts['pass']} "
                    f"| {counts['task_failure']} "
                    f"| {counts['coordination_failure']} "
                    f"| {counts['tool_error_unrecovered']} "
                    f"| {counts['incomplete']} |"
                )
        lines.append(f"")

    # ── Section 4: Efficiency (mean score on passing runs) ────────────────
    lines.append(f"## 4. Efficiency Score (passing runs only)")
    lines.append(f"")
    lines.append(f"> Score: 1.0 = optimal call count. Penalised -0.05 per extra LLM call above architecture minimum.")
    lines.append(f"")

    for task in tasks:
        lines.append(f"### {task}")
        lines.append(f"")
        header = "| Architecture |" + "".join(f" {p} mean_score | {p} mean_llm_calls |" for p in providers)
        lines.append(header)
        lines.append("|---|" + "---|---|" * len(providers))
        for arch in architectures:
            row = f"| {arch} |"
            for provider in providers:
                cell_runs = cells[(arch, task, provider)]
                row += f" {mean_metric(cell_runs, 'score')} | {mean_metric(cell_runs, None, 'num_llm_calls')} |"
            lines.append(row)
        lines.append(f"")

    # ── Section 5: task_02 coordination-specific signals ─────────────────
    lines.append(f"## 5. task_02 Coordination Signal")
    lines.append(f"")
    lines.append(f"> Key diagnostic for information asymmetry task.  ")
    lines.append(f"> `decision_saw_hold` = the decision-making agent had access to `credit_hold=True`.  ")
    lines.append(f"> `hold_in_handoff` = credit_hold appeared in peer_to_peer handoff message.  ")
    lines.append(f"> `hold_in_worker` = credit_hold appeared in supervisor_worker CRM worker summary.")
    lines.append(f"")

    def bool_rate(runs, key):
        active_runs = [r for r in runs if not r.get("skipped")]
        if not active_runs:
            return "—"
        vals = [(r.get("grade") or {}).get("metrics", {}).get(key, False) for r in active_runs]
        true_count = sum(1 for v in vals if v is True)
        return f"{true_count}/{len(vals)}"

    lines.append(f"| Architecture | Provider | decision_saw_hold | hold_in_handoff | hold_in_worker | adj_pass_rate |")
    lines.append(f"|---|---|---|---|---|---|")
    for arch in architectures:
        for provider in providers:
            cell_runs = cells.get((arch, "task_02", provider), [])
            if not cell_runs:
                continue
            s = pass_rates(cell_runs)
            lines.append(
                f"| {arch} | {provider} "
                f"| {bool_rate(cell_runs, 'decision_agent_saw_credit_hold')} "
                f"| {bool_rate(cell_runs, 'credit_hold_in_handoff')} "
                f"| {bool_rate(cell_runs, 'credit_hold_in_worker_summary')} "
                f"| {fmt_rate(s['adjusted_pass_rate'])} |"
            )
    lines.append(f"")

    # ── Section 6: Interpretation ─────────────────────────────────────────
    lines.append(f"## 6. Interpretation Notes")
    lines.append(f"")
    lines.append(f"### task_01 (Customer Escalation — all architectures can solve this)")
    lines.append(f"- Expected: all architectures pass. Variation in score reflects LLM call efficiency.")
    lines.append(f"- A task_01 failure is likely a model quality or tool invocation issue, not architectural.")
    lines.append(f"")
    lines.append(f"### task_02 (Credit Hold — information asymmetry trap)")
    lines.append(f"- `peer_to_peer`: rigid handoff schema (`HANDOFF: customer_id, tier, name, status`) does not")
    lines.append(f"  include `credit_hold`. Failure is **deterministic by design** (schema never updated).")
    lines.append(f"  This models the real-world pattern of under-specified inter-agent API contracts.")
    lines.append(f"- `supervisor_worker`: CRM Worker summarizes in free text. Whether `credit_hold` appears")
    lines.append(f"  in the summary is **model-dependent and probabilistic**. Variance across trials is the signal.")
    lines.append(f"- `single_agent` / `debate_critic`: Should pass reliably. Failures here indicate model")
    lines.append(f"  reasoning errors unrelated to coordination.")
    lines.append(f"")
    lines.append(f"### On `incomplete` runs")
    lines.append(f"- These are quota (429) or crash failures. They are **infrastructure noise**, not")
    lines.append(f"  architecture signal. Adjusted pass rate (excluding them) is the primary metric.")
    lines.append(f"- Raw pass rate is shown for transparency. A high incomplete count in a specific")
    lines.append(f"  architecture (e.g. supervisor_worker making more LLM calls) is itself real signal")
    lines.append(f"  about infrastructure cost of that architecture.")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"*Generated by `report_generator.py`*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Agent Arena — Report Generator")
    parser.add_argument("manifest", help="Path to sweep manifest JSON")
    parser.add_argument(
        "--output", default=None,
        help="Output markdown file (default: results/report_<timestamp>.md)",
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    report = generate_report(manifest)

    if args.output:
        out_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = str(Path("results") / f"report_{ts}.md")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(report)

    print(report)
    print(f"\n--- Written to: {out_path} ---")


if __name__ == "__main__":
    main()
