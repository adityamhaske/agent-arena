"""Detecting drift between a run and its own history.

A model choice decays: providers update models silently, prompts drift,
traffic shifts, prices change. The arena is normally used once at a decision
point, and the decision rots from there. `arena watch` re-evaluates a project
and compares the fresh result to its own recent runs, so "we picked Haiku
three weeks ago" stays an answer instead of a snapshot.

This is a different question from :mod:`agent_arena.core.statistics`, which
resamples *within one run* to ask whether two models are really different from
each other. This asks a time-series question about *one* model against its own
past — did it get worse, not is it worse than something else — so the
comparison is a plain difference, not a resampled interval.
"""

from __future__ import annotations

import json
import statistics
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class Drift:
    """What changed for one model since its own recent history."""

    model_key: str
    current_composite: float | None
    baseline_composite: float | None
    delta: float | None
    current_status: str
    previous_status: str | None
    status_changed: bool
    flagged: bool
    n_baseline_runs: int

    @property
    def sentence(self) -> str:
        if self.status_changed:
            return (
                f"{self.model_key} changed status: {self.previous_status} -> "
                f"{self.current_status}."
            )
        if self.current_composite is None:
            if self.current_status == "no_data":
                return f"{self.model_key}: skipped this run (missing credentials or unreachable)."
            if self.current_status == "failed":
                return (
                    f"{self.model_key}: disqualified this run — see the leaderboard "
                    "for which constraint it failed."
                )
            return f"{self.model_key}: no composite this run."
        if self.baseline_composite is None:
            return f"{self.model_key}: first watch run — no history to compare against yet."
        direction = "dropped" if self.delta < 0 else "improved by"
        points = abs(self.delta) * 100
        return (
            f"{self.model_key} {direction} {points:.0f} points versus its last "
            f"{self.n_baseline_runs} run(s) "
            f"({self.baseline_composite * 100:.0f}% -> {self.current_composite * 100:.0f}%)."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_key": self.model_key,
            "current_composite": self.current_composite,
            "baseline_composite": self.baseline_composite,
            "delta": self.delta,
            "current_status": self.current_status,
            "previous_status": self.previous_status,
            "status_changed": self.status_changed,
            "flagged": self.flagged,
            "sentence": self.sentence,
        }


def compare_to_history(
    model_key: str,
    current_composite: float | None,
    current_status: str,
    history: Sequence[dict[str, Any]],
    threshold: float = 0.05,
) -> Drift:
    """One model's drift, given its history newest-first, INCLUDING this run.

    ``history[0]`` is the run just recorded; everything after it is the
    baseline. Comparing to the *mean* of prior runs rather than only the one
    immediately before absorbs a single noisy run instead of chasing it.

    Status changes are compared against the single most recent prior run —
    not "was this status ever seen before" — because a model that has been
    disqualified for weeks and stays disqualified has not just changed.
    """
    prior = list(history[1:])
    priced = [row["composite"] for row in prior if row.get("composite") is not None]
    baseline = statistics.fmean(priced) if priced else None
    delta = (
        None
        if (baseline is None or current_composite is None)
        else current_composite - baseline
    )
    previous_status = prior[0].get("status") if prior else None
    status_changed = previous_status is not None and previous_status != current_status
    flagged = status_changed or (delta is not None and abs(delta) >= threshold)
    return Drift(
        model_key=model_key,
        current_composite=current_composite,
        baseline_composite=baseline,
        delta=delta,
        current_status=current_status,
        previous_status=previous_status,
        status_changed=status_changed,
        flagged=flagged,
        n_baseline_runs=len(priced),
    )


@dataclass
class WatchReport:
    """One tick of `arena watch`: every model's drift, plus the run it came from."""

    run_id: str
    project: str
    drifts: list[Drift] = field(default_factory=list)

    @property
    def flagged(self) -> list[Drift]:
        return [d for d in self.drifts if d.flagged]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "drifts": [d.to_dict() for d in self.drifts],
        }


def notify_webhook(url: str, payload: dict[str, Any], timeout_s: float = 10.0) -> str | None:
    """POST a JSON payload. Returns an error string, or ``None`` on success.

    Never raises: a broken webhook must not make ``arena watch`` itself look
    like the evaluation failed, when only the notification did.
    """
    try:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            response.read(0)
        return None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
