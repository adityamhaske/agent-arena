"""Turning a run into something a human can act on.

Three renderings of the same data: a console summary for the terminal, a
Markdown report to commit next to the results, and JSON for whatever comes
next. All three lead with the same thing — which model to pick, and what the
choice costs you on the metrics you said you cared about.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .metrics import Leaderboard, ModelScore
from .runner import RunResult

_STATUS_LABEL = {
    "ranked": "ranked",
    "failed": "DISQUALIFIED",
    "no_data": "no data",
}


# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------


def format_metric(name: str, value: float | None) -> str:
    """Render a raw metric with the unit a reader expects."""
    if value is None:
        return "—"
    if name in ("accuracy", "pass_rate", "reliability"):
        return f"{value:.1%}"
    if name == "cost":
        return f"${value:,.2f}"
    if name in ("latency", "latency_p95"):
        return f"{value:,.0f}ms" if value >= 1 else f"{value:.2f}ms"
    if name == "tokens":
        return f"{value:,.0f}"
    if abs(value) >= 1000:
        return f"{value:,.1f}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    if not rows:
        return "_(none)_\n"
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
    return "\n".join(lines) + "\n"


def text_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    if not rows:
        return "  (none)\n"
    cells = [[str(h) for h in headers]] + [
        ["" if c is None else str(c) for c in row] for row in rows
    ]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    lines = [
        "  " + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells[0])),
        "  " + "  ".join("-" * widths[i] for i in range(len(headers))),
    ]
    for row in cells[1:]:
        lines.append("  " + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# report building
# ---------------------------------------------------------------------------


class Report:
    """Renders one :class:`~agent_arena.core.runner.RunResult`."""

    def __init__(self, run: RunResult) -> None:
        self.run = run
        self.config = run.config
        self.leaderboard: Leaderboard = run.leaderboard
        self.weighted_metrics = [
            name for name, weight in self.config.metrics.weights.items() if weight > 0
        ]

    # ---- console ------------------------------------------------------

    def console(self) -> str:
        run = self.run
        board = self.leaderboard
        out: list[str] = []

        out.append("")
        out.append(f"Agent Arena — {run.project}")
        out.append(
            f"  {len(run.config.enabled_models)} models × {len(run.test_cases)} tests "
            f"× {run.config.run.trials} trial(s) = {len(run.results)} calls "
            f"in {run.duration_s:.1f}s"
        )
        if run.total_cost_usd:
            out.append(f"  Spend: ${run.total_cost_usd:.4f}")
        if run.error_count:
            out.append(f"  Failed calls: {run.error_count}")
        out.append("")

        headers = ["#", "model", "id", "composite", *self.weighted_metrics, "status"]
        rows = []
        for entry in board.entries:
            rows.append(
                [
                    entry.rank if entry.rank else "-",
                    entry.key,
                    entry.model,
                    f"{entry.composite:.3f}" if entry.composite is not None else "—",
                    *[format_metric(m, entry.raw(m)) for m in self.weighted_metrics],
                    _STATUS_LABEL.get(entry.status, entry.status),
                ]
            )
        out.append(text_table(headers, rows))

        winner = board.winner
        if winner:
            out.append(f"  Winner: {winner.key}  ({self._why(winner)})")
        else:
            out.append("  No model qualified — see the disqualifications below.")

        for entry in board.disqualified:
            out.append(f"  ✗ {entry.key}: {'; '.join(entry.failures)}")
        for entry in board.entries:
            if entry.status == "no_data":
                out.append(f"  · {entry.key}: {'; '.join(entry.failures) or 'no data'}")

        for note in board.notes:
            out.append(f"  ! {note}")

        out.append("")
        out.append(f"  Run id: {run.run_id}   DB: {self.config.database}")
        return "\n".join(out)

    # ---- markdown -----------------------------------------------------

    def markdown(self) -> str:
        run, board = self.run, self.leaderboard
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        weights = self.config.metrics.normalized_weights()

        md: list[str] = []
        md.append(f"# {run.project} — model evaluation\n")
        if self.config.description:
            md.append(f"{self.config.description}\n")

        winner = board.winner
        md.append("## Recommendation\n")
        if winner:
            label = f" — {winner.display}" if winner.display and winner.display != winner.key else ""
            # A ranked model can still have no composite, when every weighted
            # metric was unmeasurable. Crashing the report here would throw
            # away a sweep the user has already paid for.
            composite = (
                f"**{winner.composite:.3f}**" if winner.composite is not None else "not scored"
            )
            md.append(
                f"**`{winner.key}`**{label} (`{winner.model}`) — composite "
                f"{composite}. {self._why(winner)}\n"
            )
            runner_up = board.ranked[1] if len(board.ranked) > 1 else None
            if runner_up:
                md.append(self._tradeoff_sentence(winner, runner_up) + "\n")
        else:
            md.append(
                "No model satisfied the project's hard constraints. "
                "See *Disqualified* below.\n"
            )

        md.append("## Run\n")
        md.append(
            markdown_table(
                ["field", "value"],
                [
                    ["run id", f"`{run.run_id}`"],
                    ["generated", generated],
                    ["models", len(self.config.enabled_models)],
                    ["test cases", len(run.test_cases)],
                    ["trials per case", self.config.run.trials],
                    ["calls", len(run.results)],
                    ["failed calls", run.error_count],
                    ["wall clock", f"{run.duration_s:.1f}s"],
                    ["total spend", f"${run.total_cost_usd:.4f}" if run.total_cost_usd else "—"],
                    [
                        "weights",
                        ", ".join(f"{k} {v:.0%}" for k, v in weights.items()),
                    ],
                ],
            )
        )

        md.append("\n## Leaderboard\n")
        headers = ["#", "model", "id", "composite", *self.weighted_metrics, "status"]
        rows = []
        for entry in board.entries:
            rows.append(
                [
                    entry.rank or "—",
                    f"`{entry.key}`",
                    f"`{entry.model}`",
                    f"**{entry.composite:.3f}**" if entry.composite is not None else "—",
                    *[format_metric(m, entry.raw(m)) for m in self.weighted_metrics],
                    _STATUS_LABEL.get(entry.status, entry.status),
                ]
            )
        md.append(markdown_table(headers, rows))

        md.append("\n### Normalised contributions\n")
        md.append(
            "Each metric scaled to 0–1 (1 = best in this field), multiplied by its weight.\n\n"
        )
        contrib_headers = ["model", *[f"{m} ×{weights.get(m, 0):.2f}" for m in self.weighted_metrics], "composite"]
        contrib_rows = []
        for entry in board.ranked:
            cells = []
            for name in self.weighted_metrics:
                metric = entry.metrics.get(name)
                if metric is None or metric.normalized is None:
                    cells.append("—")
                else:
                    cells.append(
                        f"{metric.normalized:.2f} → {metric.normalized * weights.get(name, 0):.3f}"
                    )
            contrib_rows.append(
                [
                    f"`{entry.key}`",
                    *cells,
                    f"**{entry.composite:.3f}**" if entry.composite is not None else "—",
                ]
            )
        md.append(markdown_table(contrib_headers, contrib_rows))

        disqualified = board.disqualified + [e for e in board.entries if e.status == "no_data"]
        if disqualified:
            md.append("\n## Disqualified\n")
            md.append(
                markdown_table(
                    ["model", "reason"],
                    [[f"`{e.key}`", "; ".join(e.failures) or "—"] for e in disqualified],
                )
            )

        tag_section = self._tag_section()
        if tag_section:
            md.append("\n## Accuracy by tag\n")
            md.append(tag_section)

        md.append("\n## Per-test results\n")
        md.append(self._matrix_section())

        failures = self._failure_section()
        if failures:
            md.append("\n## Where models went wrong\n")
            md.append(failures)

        warnings = [(e.key, w) for e in board.entries for w in e.warnings]
        if board.notes or warnings:
            md.append("\n## Caveats\n")
            for note in board.notes:
                md.append(f"- {note}")
            for key, warning in warnings:
                md.append(f"- `{key}`: {warning}")
            md.append("")

        md.append("\n## Reproduce\n")
        md.append(f"```bash\narena evaluate --project {self.config.root}\n```\n")
        md.append(
            f"\nRaw results: `{self.config.database}` (table `results`, "
            f"run id `{run.run_id}`).\n"
        )
        return "\n".join(md)

    # ---- json ---------------------------------------------------------

    def json(self) -> str:
        payload = self.run.to_dict()
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
        return json.dumps(payload, indent=2, default=str)

    # ---- sections -----------------------------------------------------

    def _why(self, entry: ModelScore) -> str:
        bits = []
        for name in self.weighted_metrics:
            value = entry.raw(name)
            if value is not None:
                bits.append(f"{name} {format_metric(name, value)}")
        return ", ".join(bits) if bits else "no metrics recorded"

    def _tradeoff_sentence(self, winner: ModelScore, runner_up: ModelScore) -> str:
        """Say what the winner gives up, not just what it wins."""
        gives_up = []
        for name in self.weighted_metrics:
            mine, theirs = winner.raw(name), runner_up.raw(name)
            if mine is None or theirs is None:
                continue
            direction = self.config.metrics.direction(name)
            worse = mine < theirs if direction == "max" else mine > theirs
            if worse:
                gives_up.append(
                    f"{name} ({format_metric(name, mine)} vs "
                    f"{format_metric(name, theirs)})"
                )
        if winner.composite is None or runner_up.composite is None:
            return f"`{runner_up.key}` is the closest alternative."
        margin = winner.composite - runner_up.composite
        sentence = (
            f"It beats `{runner_up.key}` by {margin:.3f} on the composite"
        )
        if gives_up:
            sentence += f", while losing on {', '.join(gives_up)}"
        return sentence + "."

    def _tag_section(self) -> str:
        tags = sorted({tag for entry in self.leaderboard.entries for tag in entry.by_tag})
        if not tags:
            return ""
        rows = []
        for entry in self.leaderboard.entries:
            if not entry.by_tag:
                continue
            rows.append(
                [
                    f"`{entry.key}`",
                    *[
                        f"{entry.by_tag[tag]:.0%}" if tag in entry.by_tag else "—"
                        for tag in tags
                    ],
                ]
            )
        return markdown_table(["model", *tags], rows)

    def _matrix_section(self) -> str:
        """Mean score per model per test — where the differences actually live."""
        models = [e.key for e in self.leaderboard.entries if e.status != "no_data"]
        if not models:
            return "_(no results)_\n"

        scores: dict[tuple[str, str], list[float]] = {}
        errors: set[tuple[str, str]] = set()
        for result in self.run.results:
            key = (result.model_key, result.test_id)
            if result.status != "ok":
                errors.add(key)
            elif result.score is not None:
                scores.setdefault(key, []).append(result.score)

        rows = []
        for case in self.run.test_cases:
            cells = []
            for model_key in models:
                key = (model_key, case.id)
                values = scores.get(key)
                if values:
                    mean = sum(values) / len(values)
                    cells.append("✓" if mean >= 0.999 else ("✗" if mean <= 0.001 else f"{mean:.2f}"))
                elif key in errors:
                    cells.append("ERR")
                else:
                    cells.append("—")
            rows.append([f"`{case.id}`", case.eval_type, *cells])
        return markdown_table(["test", "eval", *models], rows)

    def _failure_section(self, limit: int = 8) -> str:
        # One row per (model, test) rather than per call, keeping the worst
        # trial. Filtering to trial 1 hid every failure that only showed up on
        # a later repeat — exactly the flaky cases most worth seeing.
        worst: dict[tuple[str, str], Any] = {}
        for r in self.run.results:
            if r.status != "ok" or r.passed is not False:
                continue
            key = (r.model_key, r.test_id)
            if key not in worst or (r.score or 0.0) < (worst[key].score or 0.0):
                worst[key] = r
        failures = sorted(
            worst.values(), key=lambda r: (r.score if r.score is not None else 0.0)
        )
        errors = [r for r in self.run.results if r.status != "ok"]

        if not failures and not errors:
            return ""

        rows = []
        for result in failures[:limit]:
            rows.append(
                [
                    f"`{result.model_key}`",
                    f"`{result.test_id}`",
                    _clip(result.output, 80),
                    _clip(str(result.reference), 40),
                    _clip(result.reason, 60),
                ]
            )
        section = markdown_table(
            ["model", "test", "output", "expected", "why it failed"], rows
        )
        if len(failures) > limit:
            section += f"\n_{len(failures) - limit} more failure(s) in the database._\n"

        if errors:
            error_rows = [
                [f"`{r.model_key}`", f"`{r.test_id}`", _clip(r.error or "", 100)]
                for r in errors[:limit]
            ]
            section += "\n**Call errors**\n\n" + markdown_table(
                ["model", "test", "error"], error_rows
            )
        return section


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def write_reports(run: RunResult, output_dir: str | Path | None = None) -> dict[str, Path]:
    """Write every format the project asked for; return the paths written."""
    report = Report(run)
    directory = Path(output_dir) if output_dir else run.config.results_dir / run.run_id
    directory.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    formats = {f.lower() for f in run.config.formats}

    if "markdown" in formats or "md" in formats:
        path = directory / "report.md"
        path.write_text(report.markdown(), encoding="utf-8")
        written["markdown"] = path

    if "json" in formats:
        path = directory / "results.json"
        path.write_text(report.json(), encoding="utf-8")
        written["json"] = path

    if "csv" in formats:
        from .store import ResultStore  # noqa: PLC0415 — avoids a cycle at import time

        path = directory / "results.csv"
        with ResultStore(run.config.database) as store:
            store.export_csv(run.run_id, path)
        written["csv"] = path

    return written


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text or "—"
    return text[:limit] + "…"
