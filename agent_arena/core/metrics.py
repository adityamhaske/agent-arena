"""From raw results to a ranked leaderboard.

Three steps, each of which a project controls entirely from config:

1. **Aggregate** every result for a model into raw metrics — accuracy, cost,
   latency, reliability, tokens, plus any custom metric a scorer emitted.
2. **Normalise** each metric to ``[0, 1]`` where higher is always better, using
   either min-max across the field or a target/budget you set.
3. **Combine** them with your weights into one composite score, after
   disqualifying anything that fails a hard constraint.

Two decisions worth knowing about, because they change what the numbers mean:

* ``accuracy`` is measured over *completed* calls only. Failures are counted
  separately as ``reliability`` so that a model which errors most of the time
  cannot look accurate by answering the few calls that survived. If you do not
  weight ``reliability`` and errors occurred, the report says so.
* A metric that cannot be measured for a model (typically cost, when no
  pricing is known) does not score zero — its weight is redistributed across
  that model's measurable metrics and the omission is reported. Scoring it
  zero would punish a model for a gap in *our* catalog.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..connectors.registry import resolve_provider
from .config import ProjectConfig

_EPSILON = 1e-12


@dataclass
class MetricValue:
    """One metric for one model."""

    name: str
    raw: float | None
    normalized: float | None
    weight: float
    direction: str
    mode: str
    unit: str = ""

    @property
    def known(self) -> bool:
        return self.raw is not None and self.normalized is not None


@dataclass
class ModelScore:
    """A model's line on the leaderboard."""

    key: str
    model: str
    provider: str = ""
    display: str = ""
    status: str = "ranked"  # ranked | failed | no_data
    composite: float | None = None
    rank: int | None = None
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    by_tag: dict[str, float] = field(default_factory=dict)
    card: Any = None

    @property
    def ranked(self) -> bool:
        return self.status == "ranked"

    def raw(self, name: str) -> float | None:
        metric = self.metrics.get(name)
        return metric.raw if metric else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "model": self.model,
            "provider": self.provider,
            "display": self.display or self.key,
            "status": self.status,
            "composite": self.composite,
            "rank": self.rank,
            "metrics": {
                name: {
                    "raw": m.raw,
                    "normalized": m.normalized,
                    "weight": m.weight,
                    "direction": m.direction,
                    "unit": m.unit,
                }
                for name, m in self.metrics.items()
            },
            "failures": list(self.failures),
            "warnings": list(self.warnings),
            "stats": dict(self.stats),
            "by_tag": dict(self.by_tag),
        }


@dataclass
class Leaderboard:
    """The ranked field, plus why it came out that way."""

    entries: list[ModelScore] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    #: Confidence intervals and the paired comparison of the top two, when
    #: statistics are enabled. Attached rather than computed here: the ranking
    #: and the evidence for it are separate questions, and a stored run can be
    #: re-scored without recomputing intervals.
    statistics: Any = None

    @property
    def ranked(self) -> list[ModelScore]:
        return [e for e in self.entries if e.ranked]

    @property
    def disqualified(self) -> list[ModelScore]:
        return [e for e in self.entries if e.status == "failed"]

    @property
    def winner(self) -> ModelScore | None:
        ranked = self.ranked
        return ranked[0] if ranked else None

    def get(self, key: str) -> ModelScore | None:
        for entry in self.entries:
            if entry.key == key:
                return entry
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": dict(self.weights),
            "notes": list(self.notes),
            "winner": self.winner.key if self.winner else None,
            "entries": [e.to_dict() for e in self.entries],
        }


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

#: Human-readable units, used by the report.
METRIC_UNITS = {
    "accuracy": "0-1",
    "pass_rate": "0-1",
    "reliability": "0-1",
    "cost": "USD/1k calls",
    "latency": "ms",
    "latency_p95": "ms",
    "tokens": "tokens/call",
}


def aggregate_model(results: Sequence[Any], weights_by_test: dict[str, float]) -> dict[str, Any]:
    """Reduce one model's results into raw metric values.

    ``results`` are :class:`~agent_arena.core.runner.CallResult` objects (or
    anything with the same attributes).
    """
    attempted = len(results)
    completed = [r for r in results if r.status == "ok"]
    errored = [r for r in results if r.status != "ok"]

    stats: dict[str, Any] = {
        "attempted": attempted,
        "completed": len(completed),
        "errors": len(errored),
    }

    raw: dict[str, float | None] = {}

    # --- accuracy / pass rate (weighted by each test's own weight) ---
    total_weight = 0.0
    weighted_score = 0.0
    weighted_pass = 0.0
    graded = 0
    for result in completed:
        if result.score is None:
            continue
        weight = weights_by_test.get(result.test_id, 1.0)
        total_weight += weight
        weighted_score += weight * float(result.score)
        weighted_pass += weight * (1.0 if result.passed else 0.0)
        graded += 1

    raw["accuracy"] = (weighted_score / total_weight) if total_weight > 0 else None
    raw["pass_rate"] = (weighted_pass / total_weight) if total_weight > 0 else None
    raw["reliability"] = (len(completed) / attempted) if attempted else None
    stats["graded"] = graded

    # --- cost ---
    costs = [r.cost_usd for r in completed if r.cost_usd is not None]
    if costs and len(costs) == len(completed):
        mean_cost = sum(costs) / len(costs)
        raw["cost"] = mean_cost * 1000.0  # USD per 1,000 calls
        stats["total_cost_usd"] = sum(costs)
        stats["cost_per_call_usd"] = mean_cost
    else:
        raw["cost"] = None
        stats["total_cost_usd"] = sum(costs) if costs else None
        stats["cost_priced_calls"] = len(costs)

    # --- latency ---
    latencies = [r.latency_ms for r in completed if r.latency_ms is not None]
    raw["latency"] = (sum(latencies) / len(latencies)) if latencies else None
    raw["latency_p95"] = percentile(latencies, 95) if latencies else None
    stats["latency_p50"] = percentile(latencies, 50) if latencies else None
    stats["latency_max"] = max(latencies) if latencies else None

    # --- tokens ---
    token_counts = [
        (r.input_tokens or 0) + (r.output_tokens or 0)
        for r in completed
        if r.input_tokens is not None or r.output_tokens is not None
    ]
    raw["tokens"] = (sum(token_counts) / len(token_counts)) if token_counts else None
    stats["total_tokens"] = sum(token_counts) if token_counts else 0

    # --- custom metrics emitted by scorers / hooks ---
    custom: dict[str, list[float]] = {}
    for result in completed:
        for name, value in (result.metrics or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                custom.setdefault(name, []).append(float(value))
    for name, values in custom.items():
        if name not in raw:
            raw[name] = sum(values) / len(values)

    # --- accuracy by tag, for the breakdown table ---
    by_tag: dict[str, list[float]] = {}
    for result in completed:
        if result.score is None:
            continue
        for tag in result.tags or []:
            by_tag.setdefault(tag, []).append(float(result.score))

    return {
        "raw": raw,
        "stats": stats,
        "by_tag": {tag: sum(v) / len(v) for tag, v in sorted(by_tag.items())},
        "errors": [r.error for r in errored if r.error][:5],
    }


def percentile(values: Iterable[float], pct: float) -> float | None:
    """Linear-interpolated percentile. ``None`` for an empty series."""
    data = sorted(float(v) for v in values)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    position = (len(data) - 1) * (pct / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return data[int(position)]
    return data[lower] + (data[upper] - data[lower]) * (position - lower)


# ---------------------------------------------------------------------------
# normalisation + composite
# ---------------------------------------------------------------------------


def normalize(
    value: float | None,
    *,
    mode: str,
    direction: str,
    target: float | None,
    low: float | None,
    high: float | None,
) -> float | None:
    """Map a raw metric onto ``[0, 1]`` where 1 is always best.

    ``target``/``budget`` mode is absolute — a model's score does not depend on
    who else is in the run:

    * lower-is-better (cost, latency): the target is a **ceiling**, and the
      score is the headroom left under it — ``1 - value/target``. Free scores
      1.0, half the budget scores 0.5, at or over budget scores 0.0.
    * higher-is-better: the target is a **goal**, and the score is the fraction
      of it reached — ``value/target``, capped at 1.0.

    ``minmax`` mode is relative: best in the field scores 1.0, worst 0.0. Use
    it when you have no absolute number in mind and only want a ranking.
    """
    if value is None:
        return None

    if mode == "raw":
        return _clamp(value)

    if mode in ("target", "budget"):
        if not target:
            return _clamp(value)
        if direction == "min":
            return _clamp(1.0 - (value / target))
        return _clamp(value / target)

    # minmax across the field
    if low is None or high is None:
        return _clamp(value)
    if abs(high - low) < _EPSILON:
        # Everyone tied on this metric — it carries no information, so it
        # should not swing the composite in either direction.
        return 1.0
    if direction == "min":
        return _clamp((high - value) / (high - low))
    return _clamp((value - low) / (high - low))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def build_leaderboard(
    config: ProjectConfig,
    results_by_model: dict[str, Sequence[Any]],
    model_specs: Sequence[Any],
    price_book: Any = None,
    weights_by_test: dict[str, float] | None = None,
) -> Leaderboard:
    """Score, gate and rank every model in the run."""
    weights_by_test = weights_by_test or {}
    weights = config.metrics.normalized_weights()
    board = Leaderboard(weights=weights)

    aggregates: dict[str, dict[str, Any]] = {}
    entries: dict[str, ModelScore] = {}

    for spec in model_specs:
        results = results_by_model.get(spec.key, [])
        provider = resolve_provider(spec)
        card = price_book.get(spec.model, provider=provider) if price_book else None
        entry = ModelScore(
            key=spec.key,
            model=spec.model,
            provider=(provider or (card.provider if card else "") or ""),
            display=spec.display,
            card=card,
        )
        aggregate = aggregate_model(results, weights_by_test)
        aggregates[spec.key] = aggregate
        entry.stats = aggregate["stats"]
        entry.by_tag = aggregate["by_tag"]

        if not results:
            entry.status = "no_data"
            entry.failures.append("no results recorded")
        elif aggregate["stats"]["completed"] == 0:
            entry.status = "no_data"
            sample = aggregate["errors"][0] if aggregate["errors"] else "unknown error"
            entry.failures.append(f"every call failed — {sample}")

        _check_constraints(entry, config.constraints, aggregate["raw"], aggregate["stats"], card)
        entries[spec.key] = entry

    # Ranges are computed over the *eligible* field only: a disqualified model
    # must not stretch the min-max scale that everyone else is judged on.
    eligible = [key for key, entry in entries.items() if entry.status == "ranked"]
    ranges = _metric_ranges(
        [aggregates[key]["raw"] for key in eligible], set(weights) | set(_all_metric_names(aggregates))
    )

    for key, entry in entries.items():
        raw = aggregates[key]["raw"]
        entry.metrics = _build_metric_values(config, raw, weights, ranges)
        if entry.status == "ranked":
            entry.composite, redistributed = _composite(entry.metrics, weights)
            for name in redistributed:
                entry.warnings.append(
                    f"{name} could not be measured; its weight was redistributed "
                    "across the remaining metrics"
                )

    board.entries = _rank(list(entries.values()), config.metrics.tie_breaker)
    board.notes = _leaderboard_notes(config, board, aggregates, results_by_model)
    return board


def _all_metric_names(aggregates: dict[str, dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for aggregate in aggregates.values():
        names.update(aggregate["raw"])
    return names


def _metric_ranges(
    raws: Sequence[dict[str, float | None]], names: Iterable[str]
) -> dict[str, tuple[float | None, float | None]]:
    ranges: dict[str, tuple[float | None, float | None]] = {}
    for name in names:
        values = [r[name] for r in raws if r.get(name) is not None]
        ranges[name] = (min(values), max(values)) if values else (None, None)
    return ranges


def _build_metric_values(
    config: ProjectConfig,
    raw: dict[str, float | None],
    weights: dict[str, float],
    ranges: dict[str, tuple[float | None, float | None]],
) -> dict[str, MetricValue]:
    metrics: dict[str, MetricValue] = {}
    # Weighted metrics first (report order), then everything else measured.
    names = list(weights) + [n for n in raw if n not in weights]
    for name in names:
        direction = config.metrics.direction(name)
        mode = config.metrics.normalize_mode(name)
        target = config.metrics.targets.get(name)
        low, high = ranges.get(name, (None, None))
        value = raw.get(name)
        metrics[name] = MetricValue(
            name=name,
            raw=value,
            normalized=normalize(
                value, mode=mode, direction=direction, target=target, low=low, high=high
            ),
            weight=weights.get(name, 0.0),
            direction=direction,
            mode=mode,
            unit=METRIC_UNITS.get(name, ""),
        )
    return metrics


def _composite(
    metrics: dict[str, MetricValue], weights: dict[str, float]
) -> tuple[float | None, list[str]]:
    usable = {
        name: metrics[name]
        for name, weight in weights.items()
        if weight > 0 and name in metrics and metrics[name].known
    }
    missing = [
        name
        for name, weight in weights.items()
        if weight > 0 and (name not in metrics or not metrics[name].known)
    ]
    if not usable:
        return None, missing

    total_weight = sum(weights[name] for name in usable)
    score = sum(metrics[name].normalized * weights[name] for name in usable) / total_weight
    return score, missing


def _check_constraints(
    entry: ModelScore,
    constraints: Any,
    raw: dict[str, float | None],
    stats: dict[str, Any],
    card: Any,
) -> None:
    """Apply hard gates. Anything failing is excluded from the ranking."""
    failures: list[str] = []

    if card is None or not card.known:
        if not constraints.allow_unknown_card and constraints.any_static:
            failures.append(
                f"no model card for {entry.model!r} and constraints.allow_unknown_card is false"
            )
        elif constraints.required_features or constraints.privacy_required:
            entry.warnings.append(
                f"no model card for {entry.model!r} — capability and privacy constraints "
                "could not be verified; add it under `pricing.models` in your config"
            )
    else:
        if constraints.required_features:
            missing = card.missing_features(constraints.required_features)
            if missing:
                failures.append(f"missing required feature(s): {', '.join(missing)}")
        if constraints.privacy_required:
            missing = card.missing_privacy(constraints.privacy_required)
            if missing:
                failures.append(
                    f"privacy requirement(s) not met or not declared: {', '.join(missing)}"
                )
        if constraints.min_context_tokens:
            if card.context_tokens is None:
                entry.warnings.append("context window unknown; min_context_tokens not verified")
            elif card.context_tokens < constraints.min_context_tokens:
                failures.append(
                    f"context window {card.context_tokens:,} < required "
                    f"{constraints.min_context_tokens:,}"
                )

    accuracy = raw.get("accuracy")
    if constraints.min_accuracy is not None and accuracy is not None:
        if accuracy < constraints.min_accuracy:
            failures.append(
                f"accuracy {accuracy:.1%} below the required {constraints.min_accuracy:.1%}"
            )

    if constraints.max_error_rate is not None and stats.get("attempted"):
        error_rate = stats["errors"] / stats["attempted"]
        if error_rate > constraints.max_error_rate:
            failures.append(
                f"error rate {error_rate:.1%} above the allowed {constraints.max_error_rate:.1%}"
            )

    cost = raw.get("cost")
    if constraints.max_cost_per_1k_calls_usd is not None and cost is not None:
        if cost > constraints.max_cost_per_1k_calls_usd:
            failures.append(
                f"cost ${cost:.2f}/1k calls above the budget "
                f"${constraints.max_cost_per_1k_calls_usd:.2f}"
            )

    p95 = raw.get("latency_p95")
    if constraints.max_latency_p95_ms is not None and p95 is not None:
        if p95 > constraints.max_latency_p95_ms:
            failures.append(
                f"p95 latency {p95:.0f}ms above the allowed {constraints.max_latency_p95_ms:.0f}ms"
            )

    if failures:
        entry.failures.extend(failures)
        if entry.status == "ranked":
            entry.status = "failed"


def _rank(entries: list[ModelScore], tie_breaker: str) -> list[ModelScore]:
    def sort_key(entry: ModelScore):
        composite = entry.composite if entry.composite is not None else -1.0
        breaker = entry.raw(tie_breaker)
        breaker = breaker if breaker is not None else -1.0
        return (-composite, -breaker, entry.key)

    ranked = sorted([e for e in entries if e.ranked], key=sort_key)
    for position, entry in enumerate(ranked, start=1):
        entry.rank = position

    others = sorted(
        [e for e in entries if not e.ranked], key=lambda e: (e.status != "failed", e.key)
    )
    return ranked + others


def _leaderboard_notes(
    config: ProjectConfig,
    board: Leaderboard,
    aggregates: dict[str, dict[str, Any]],
    results_by_model: dict[str, Sequence[Any]],
) -> list[str]:
    notes: list[str] = []

    if "reliability" not in config.metrics.weights:
        total_errors = sum(a["stats"].get("errors", 0) for a in aggregates.values())
        if total_errors:
            notes.append(
                f"{total_errors} call(s) failed and were excluded from accuracy. "
                "Add `reliability` to metrics.weights to make failures count against a model."
            )

    # Models whose cost could not be measured at all — which is what actually
    # causes the weight to be redistributed. A missing price card is only one
    # way to get there: a connector that reports its own spend (a `run:` target
    # knows its real end-to-end cost) has a cost metric with no card at all, and
    # must not be reported as excluded.
    unpriced = [
        entry.model
        for entry in board.entries
        if entry.status != "no_data" and aggregates.get(entry.key, {}).get("raw", {}).get("cost")
        is None
    ]
    if unpriced and config.metrics.weights.get("cost"):
        notes.append(
            "No cost measured for " + ", ".join(sorted(set(unpriced))) + ". Cost was left "
            "out of their composite (weight redistributed). Add prices under "
            "`pricing.models`, or return a `cost_usd` from a `run:` target."
        )

    if len(board.ranked) == 1 and board.disqualified:
        notes.append(
            "Only one model cleared the hard constraints, so the ranking is not a comparison."
        )

    ranked = board.ranked
    if (
        len(ranked) >= 2
        and ranked[0].composite is not None
        and ranked[1].composite is not None
    ):
        margin = ranked[0].composite - ranked[1].composite
        if margin < 0.02:
            # Telling someone to run more trials is useless advice when the
            # trials they already ran were identical — then the sweep is
            # under-powered on *cases*, not on repeats.
            varied = _trials_varied(results_by_model)
            if varied is False:
                remedy = (
                    "Repeated trials produced identical scores, so more trials will not "
                    "separate them — add test cases instead."
                )
            else:
                remedy = "Raise run.trials or add test cases before trusting the order."
            notes.append(
                f"{ranked[0].key} beat {ranked[1].key} by {margin:.3f} — within noise for a "
                f"small sweep. {remedy}"
            )
    return notes


def _trials_varied(results_by_model: dict[str, Sequence[Any]]) -> bool | None:
    """Did repeating a case ever change its score?

    ``None`` when nothing was repeated, ``False`` when every repeat matched
    (deterministic at this temperature), ``True`` when outputs moved.
    """
    first_seen: dict[tuple[str, str], float] = {}
    repeated = False
    for results in results_by_model.values():
        for result in results:
            if result.status != "ok" or result.score is None:
                continue
            key = (result.model_key, result.test_id)
            if key in first_seen:
                repeated = True
                if abs(first_seen[key] - float(result.score)) > 1e-9:
                    return True
            else:
                first_seen[key] = float(result.score)
    return False if repeated else None
