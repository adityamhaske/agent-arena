"""Turning the engine's numbers into sentences a non-technical person can act on.

The arena's output is already honest, but it is written for someone who knows
what a composite score is. An operations lead choosing a model for their support
queue does not, and should not have to.

Everything in here is a pure function over already-computed results. It adds no
judgement of its own: the ranking, the disqualifications and the notes all come
from :mod:`agent_arena.core.metrics`. This module only re-words them. If it ever
disagreed with the CLI's report, the CLI would be right and this would be a bug.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# what are you evaluating? — job presets
# ---------------------------------------------------------------------------

#: The wizard's first real question. A non-technical user knows what their
#: system is supposed to *do*; they do not know what `json_match` is. Each
#: preset is one answer to "what job is the AI doing?", and carries everything
#: needed to write a working config for it.
JOB_PRESETS: list[dict[str, Any]] = [
    {
        "id": "sort",
        "title": "Sort things into categories",
        "blurb": "Every answer must be one of a fixed set of labels.",
        "example": "Routing support tickets to billing / technical / refund.",
        "eval_type": "classification",
        "answer_label": "Which category is correct?",
        "answer_hint": "billing",
        "needs_labels": True,
        "max_tokens": 8,
        "system": (
            "You are a classifier. Reply with exactly one label from the list "
            "and nothing else."
        ),
        "weights": {"accuracy": 0.55, "cost": 0.25, "latency": 0.20},
    },
    {
        "id": "extract",
        "title": "Pull specific details out of text",
        "blurb": "The answer is a set of fields — a form filled in from a document.",
        "example": "Reading an invoice into {total, date, vendor}.",
        "eval_type": "json_match",
        "answer_label": "What should the extracted fields be?",
        "answer_hint": '{"total": 249.99, "vendor": "Acme"}',
        "needs_labels": False,
        "max_tokens": 400,
        "system": (
            "Extract the requested fields. Reply with JSON only — no explanation, "
            "no markdown fence."
        ),
        "weights": {"accuracy": 0.70, "cost": 0.15, "latency": 0.15},
    },
    {
        "id": "answer",
        "title": "Answer questions",
        "blurb": "A written answer that has to mean the same thing as the reference.",
        "example": "A support assistant answering 'how do I reset my password?'",
        "eval_type": "semantic",
        "answer_label": "What is a good answer?",
        "answer_hint": "Open Settings → Security → Reset password.",
        "needs_labels": False,
        "max_tokens": 500,
        "system": "Answer the question accurately and concisely.",
        "weights": {"accuracy": 0.65, "cost": 0.15, "latency": 0.20},
    },
    {
        "id": "find",
        "title": "Find a specific fact",
        "blurb": "The answer is right if it contains the thing you are looking for.",
        "example": "Pulling the order number out of a customer email.",
        "eval_type": "contains",
        "answer_label": "What must the answer contain?",
        "answer_hint": "ORD-4417",
        "needs_labels": False,
        "max_tokens": 200,
        "system": "Answer with the requested detail.",
        "weights": {"accuracy": 0.70, "cost": 0.15, "latency": 0.15},
    },
    {
        "id": "number",
        "title": "Calculate a number",
        "blurb": "The answer is a number, correct within a tolerance you set.",
        "example": "Totalling line items, or estimating a delivery window.",
        "eval_type": "numeric",
        "answer_label": "What is the correct number?",
        "answer_hint": "249.99",
        "needs_labels": False,
        "max_tokens": 64,
        "system": "Reply with the number only.",
        "weights": {"accuracy": 0.75, "cost": 0.10, "latency": 0.15},
    },
    {
        "id": "write",
        "title": "Write or summarise",
        "blurb": (
            "Longer text with no single right answer, graded by a second AI "
            "against your notes on what a good answer looks like."
        ),
        "example": "Summarising a research paper for a newsletter.",
        "eval_type": "llm_judge",
        "answer_label": "What does a good answer look like?",
        "answer_hint": "Covers the method, the result and the main limitation.",
        "needs_labels": False,
        "max_tokens": 1000,
        "system": "Write clearly and stick to what the source supports.",
        "weights": {"accuracy": 0.70, "cost": 0.20, "latency": 0.10},
        "caution": (
            "Grading with an AI judge costs money on top of the run itself, and "
            "a judge can be wrong. Spot-check a few answers yourself."
        ),
    },
    {
        "id": "exact",
        "title": "Match an exact answer",
        "blurb": "The answer must be the expected text, ignoring case and punctuation.",
        "example": "Normalising a country name to its ISO code.",
        "eval_type": "exact_match",
        "answer_label": "What is the exact answer?",
        "answer_hint": "GB",
        "needs_labels": False,
        "max_tokens": 32,
        "system": "Reply with the answer only.",
        "weights": {"accuracy": 0.60, "cost": 0.20, "latency": 0.20},
    },
]

PRESETS_BY_ID = {preset["id"]: preset for preset in JOB_PRESETS}


def preset_for_eval_type(eval_type: str) -> dict[str, Any] | None:
    """The preset that produced this eval type, for describing a loaded project."""
    for preset in JOB_PRESETS:
        if preset["eval_type"] == eval_type:
            return preset
    return None


# ---------------------------------------------------------------------------
# metric vocabulary
# ---------------------------------------------------------------------------

#: ``label`` heads the results column; ``question`` is what the metric answers,
#: shown on hover and beside the weight sliders.
METRIC_LANGUAGE: dict[str, dict[str, str]] = {
    "accuracy": {
        "label": "Gets it right",
        "question": "How often is the answer correct?",
        "slider": "Being right",
        "better": "high",
    },
    "pass_rate": {
        "label": "Passes your check",
        "question": "How often does the answer clear your pass mark?",
        "slider": "Passing your check",
        "better": "high",
    },
    "reliability": {
        "label": "Answers at all",
        "question": "How often does the model reply without erroring out?",
        "slider": "Answering without errors",
        "better": "high",
    },
    "cost": {
        "label": "Cost per 1,000",
        "question": "What do 1,000 uses cost you?",
        "slider": "Staying cheap",
        "better": "low",
    },
    "latency": {
        "label": "Typical wait",
        "question": "How long does someone wait for an answer?",
        "slider": "Being fast",
        "better": "low",
    },
    "latency_p95": {
        "label": "Slow-day wait",
        "question": "How long do the slowest 5% of answers take?",
        "slider": "Avoiding slow outliers",
        "better": "low",
    },
    "tokens": {
        "label": "Length of answer",
        "question": "How much text does the model produce per answer?",
        "slider": "Keeping answers short",
        "better": "low",
    },
}


def metric_label(name: str) -> str:
    return METRIC_LANGUAGE.get(name, {}).get("label", name.replace("_", " ").capitalize())


def metric_question(name: str) -> str:
    return METRIC_LANGUAGE.get(name, {}).get("question", f"What is this project's {name}?")


def slider_label(name: str) -> str:
    return METRIC_LANGUAGE.get(name, {}).get("slider", metric_label(name))


# ---------------------------------------------------------------------------
# formatting numbers as phrases
# ---------------------------------------------------------------------------


def out_of_100(fraction: float | None) -> str:
    """``0.833`` → ``"83 out of 100"``. The single most useful translation here."""
    if fraction is None:
        return "not measured"
    return f"{round(fraction * 100)} out of 100"


def percent(fraction: float | None, places: int = 0) -> str:
    if fraction is None:
        return "—"
    return f"{fraction * 100:.{places}f}%"


def money(usd: float | None, per: str = "1,000 uses") -> str:
    """Cost, in units a person can picture rather than dollars-per-million-tokens."""
    if usd is None:
        return "not measured"
    if usd == 0:
        return "free"
    if usd < 0.01:
        return f"under a cent per {per}"
    if usd < 1:
        return f"{usd * 100:.0f}¢ per {per}"
    if usd < 1000:
        return f"${usd:,.2f} per {per}"
    return f"${usd:,.0f} per {per}"


def duration(ms: float | None) -> str:
    if ms is None:
        return "not measured"
    if ms < 1000:
        return f"{ms:,.0f} milliseconds"
    if ms < 60_000:
        return f"{ms / 1000:.1f} seconds"
    return f"{ms / 60_000:.1f} minutes"


def speed_word(ms: float | None) -> str:
    """The feel of a wait, for someone who has no intuition for milliseconds."""
    if ms is None:
        return "unknown"
    if ms < 300:
        return "instant"
    if ms < 1000:
        return "fast"
    if ms < 3000:
        return "a short pause"
    if ms < 10_000:
        return "a noticeable wait"
    return "slow"


def ratio_phrase(better: float | None, worse: float | None, unit: str) -> str | None:
    """``"5× cheaper"``. ``None`` when the comparison would be meaningless."""
    if not better or not worse or better <= 0 or worse <= 0:
        return None
    if worse / better < 1.15:  # under 15% apart is not worth a sentence
        return None
    return f"{worse / better:.1f}× {unit}"


# ---------------------------------------------------------------------------
# describing the choice the user made
# ---------------------------------------------------------------------------


def explain_weights(weights: dict[str, float]) -> str:
    """Render the weights as a sentence: "You care most about being right (55%)…"."""
    ordered = sorted(
        ((name, w) for name, w in weights.items() if w > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if not ordered:
        return "You have not said what matters yet."
    parts = [f"{slider_label(name).lower()} ({round(w * 100)}%)" for name, w in ordered]
    if len(parts) == 1:
        return f"You care only about {parts[0]}."
    return f"You care most about {parts[0]}, then " + ", then ".join(parts[1:]) + "."


def explain_constraints(constraints: dict[str, Any]) -> list[str]:
    """Each non-negotiable as one plain sentence.

    Keys match :class:`agent_arena.core.config.Constraints` exactly — a
    requirement the UI names but the engine does not enforce would be a lie.
    """
    lines = []
    min_accuracy = constraints.get("min_accuracy")
    if min_accuracy is not None:
        lines.append(
            f"A model must get at least {out_of_100(min_accuracy)} right, "
            "or it is ruled out entirely."
        )
    max_cost = constraints.get("max_cost_per_1k_calls_usd")
    if max_cost is not None:
        lines.append(f"It must cost no more than {money(max_cost)}.")
    max_p95 = constraints.get("max_latency_p95_ms")
    if max_p95 is not None:
        lines.append(
            f"Even on a slow day, answers must arrive within {duration(max_p95)}."
        )
    max_error_rate = constraints.get("max_error_rate")
    if max_error_rate is not None:
        lines.append(
            f"No more than {out_of_100(max_error_rate)} of attempts may fail outright."
        )
    min_context = constraints.get("min_context_tokens")
    if min_context:
        lines.append(
            f"It must be able to read at least {int(min_context):,} tokens at once "
            "(roughly {:,} words).".format(int(min_context) * 3 // 4)
        )
    for feature in constraints.get("required_features") or []:
        lines.append(f"It must support {str(feature).replace('_', ' ')}.")
    for rule in constraints.get("privacy_required") or []:
        lines.append(f"It must meet your {str(rule).replace('_', ' ')} requirement.")
    return lines


# ---------------------------------------------------------------------------
# describing the result
# ---------------------------------------------------------------------------

#: Below this gap in composite score, a 12-case sweep genuinely cannot tell two
#: models apart, and the UI must say so rather than crowning one.
TOO_CLOSE = 0.02


def _raw(entry: dict[str, Any], metric: str) -> float | None:
    return (entry.get("metrics", {}).get(metric) or {}).get("raw")


def summarise_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """One leaderboard row, with every number also rendered as a phrase."""
    accuracy = _raw(entry, "accuracy")
    cost = _raw(entry, "cost")
    latency = _raw(entry, "latency")
    return {
        "key": entry.get("key"),
        "display": entry.get("display") or entry.get("key"),
        "model": entry.get("model"),
        "provider": entry.get("provider"),
        "status": entry.get("status"),
        "rank": entry.get("rank"),
        "composite": entry.get("composite"),
        "accuracy": accuracy,
        "cost": cost,
        "latency": latency,
        "plain": {
            "accuracy": out_of_100(accuracy),
            "cost": money(cost),
            "latency": duration(latency),
            "speed": speed_word(latency),
        },
        "failures": entry.get("failures", []),
        "warnings": entry.get("warnings", []),
        "stats": entry.get("stats", {}),
    }


def explain_disqualification(entry: dict[str, Any]) -> dict[str, str]:
    """Why a model was ruled out, and what the user can do about it.

    The engine already writes a precise reason; a person reading it needs to
    know whether the model is bad or their own bar is too high, so we say both.
    """
    reasons = entry.get("failures") or ["it did not meet your requirements"]
    display = entry.get("display") or entry.get("key")
    return {
        "model": display,
        "headline": f"Cannot use: {display}.",
        "reason": _plain_failure(reasons[0], entry),
        "technical": "; ".join(reasons),
        "fix": (
            "If this model is one you need, either lower that requirement or "
            "improve the prompt and run again."
        ),
    }


def _plain_failure(reason: str, entry: dict[str, Any]) -> str:
    """Re-word the engine's constraint message without losing the numbers."""
    lowered = reason.lower()
    if "accuracy" in lowered:
        got = out_of_100(_raw(entry, "accuracy"))
        return f"It only gets {got} right, which is below the floor you set."
    if "latency" in lowered:
        return (
            f"It is too slow — a typical answer takes {duration(_raw(entry, 'latency'))}, "
            "past the limit you set."
        )
    if "cost" in lowered:
        return f"It costs {money(_raw(entry, 'cost'))}, over the ceiling you set."
    if "every call failed" in lowered or "no results" in lowered:
        return "Every attempt failed, so there is nothing to judge it on."
    return reason


def explain_verdict(leaderboard: dict[str, Any]) -> dict[str, Any]:
    """The paragraph at the top of the results page.

    Answers three questions in order: who won, what winning cost you, and how
    much you should trust the answer.
    """
    entries = leaderboard.get("entries", [])
    ranked = [e for e in entries if e.get("status") == "ranked"]
    disqualified = [e for e in entries if e.get("status") == "failed"]
    weights = leaderboard.get("weights", {})

    if not ranked:
        return {
            "headline": "No model can be recommended.",
            "body": (
                "Every model you compared was either ruled out by your "
                "requirements or failed to answer. Loosen the requirements or "
                "check the models are reachable, then run again."
            ),
            "confidence": "none",
            "winner": None,
            "disqualified": [explain_disqualification(e) for e in disqualified],
            "trade_offs": [],
        }

    winner = ranked[0]
    display = winner.get("display") or winner.get("key")
    trade_offs: list[str] = []

    most_accurate = max(ranked, key=lambda e: _raw(e, "accuracy") or 0)
    cheapest = min(
        (e for e in ranked if _raw(e, "cost") is not None),
        key=lambda e: _raw(e, "cost"),
        default=None,
    )
    fastest = min(
        (e for e in ranked if _raw(e, "latency") is not None),
        key=lambda e: _raw(e, "latency"),
        default=None,
    )

    # The headline finding of nearly every real sweep: the winner is not the
    # most accurate model, and the user needs to see the trade they just made.
    if most_accurate is not winner:
        gap = (_raw(most_accurate, "accuracy") or 0) - (_raw(winner, "accuracy") or 0)
        rival = most_accurate.get("display") or most_accurate.get("key")
        line = (
            f"{display} is not the most accurate — {rival} gets about "
            f"{round(gap * 100)} more answers right in every 100"
        )
        cheaper = ratio_phrase(_raw(winner, "cost"), _raw(most_accurate, "cost"), "cheaper")
        faster = ratio_phrase(_raw(winner, "latency"), _raw(most_accurate, "latency"), "faster")
        extras = [p for p in (cheaper, faster) if p]
        if extras:
            line += " — but it is " + " and ".join(extras) + "."
        else:
            line += "."
        trade_offs.append(line)
    else:
        trade_offs.append(f"{display} is also the most accurate model you compared.")

    if cheapest is not None and cheapest is not winner:
        saving = ratio_phrase(_raw(cheapest, "cost"), _raw(winner, "cost"), "cheaper")
        if saving:
            name = cheapest.get("display") or cheapest.get("key")
            trade_offs.append(
                f"{name} is {saving}, but scores lower once your priorities are applied."
            )
    if fastest is not None and fastest is not winner:
        quicker = ratio_phrase(_raw(fastest, "latency"), _raw(winner, "latency"), "faster")
        if quicker:
            name = fastest.get("display") or fastest.get("key")
            trade_offs.append(f"{name} is {quicker}, and still did not come out ahead.")

    # Confidence: never let the UI imply a 12-case sweep separated two models
    # that a 12-case sweep cannot separate.
    confidence = "high"
    caveat = ""
    if len(ranked) > 1:
        runner_up = ranked[1]
        gap = (winner.get("composite") or 0) - (runner_up.get("composite") or 0)
        if gap < TOO_CLOSE:
            confidence = "low"
            other = runner_up.get("display") or runner_up.get("key")
            caveat = (
                f"This is too close to call: {display} and {other} are within "
                f"{gap:.3f} of each other. Add more test cases or more repeats "
                "before treating this as a decision."
            )
        elif gap < 0.08:
            confidence = "medium"
            caveat = "The top two are fairly close — more test cases would firm this up."

    body = (
        f"It gets {out_of_100(_raw(winner, 'accuracy'))} right, "
        f"costs {money(_raw(winner, 'cost'))}, and replies in "
        f"{duration(_raw(winner, 'latency'))} ({speed_word(_raw(winner, 'latency'))})."
    )

    return {
        "headline": f"Use {display}.",
        "body": body,
        "because": explain_weights(weights),
        "trade_offs": trade_offs,
        "confidence": confidence,
        "caveat": caveat,
        "winner": summarise_entry(winner),
        "disqualified": [explain_disqualification(e) for e in disqualified],
    }


def plain_notes(notes: list[str]) -> list[str]:
    """The engine's caveats, softened but not weakened."""
    out = []
    for note in notes:
        lowered = note.lower()
        if "within" in lowered and "trial" in lowered:
            out.append(
                "The top models are close enough that this run cannot separate "
                "them with confidence. Run more repeats."
            )
        elif "weight was redistributed" in lowered or "could not be measured" in lowered:
            out.append(
                "One of the things you asked us to weigh could not be measured, "
                "so its share was spread across the others."
            )
        else:
            out.append(note)
    return out


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

#: Engine errors are precise but assume a developer. The UI shows the plain
#: version and keeps the original one click away.
_ERROR_HINTS = (
    ("api key", "This model needs an API key that is not set on this machine."),
    ("cannot infer a provider", "We do not recognise that model name."),
    ("connection", "We could not reach that model's server."),
    ("timed out", "The model took too long to answer."),
    ("no test", "This project has no test cases yet. Add at least one."),
    ("missing required field", "A test case is missing something we need."),
)


def plain_error(message: str) -> str:
    lowered = str(message).lower()
    for needle, plain in _ERROR_HINTS:
        if needle in lowered:
            return plain
    return str(message)
