"""Three architectures for the same job, so the arena can rank architectures.

This is the bridge between the two halves of this repository. The multi-agent
study (`studies/multi_agent_handoff/`) found that splitting a task across agents
can lose information at the handoff, *independently of model capability* — a
`peer_to_peer` pipeline scored 0% on a task where one agent held a flag the
deciding agent needed, because the handoff format had no field for it.

That study proved the failure exists. It could not tell you what the failure
costs you, because it varied only the architecture. The arena can: give it these
three targets and it ranks them on your own accuracy, cost and latency, and
disqualifies the one that cannot clear your floor.

Everything here is deterministic and offline — no API key, no network, no
provider SDK. The "models" are simulated so the *architectural* difference is
the only thing moving, which is exactly the study's methodology.
"""

from __future__ import annotations

import re
import time

# A ticket is escalated normally, unless the account is on credit hold — then
# it must be put on hold instead. This is the study's `task_02` in miniature:
# one fact, held by the first stage, that the deciding stage needs.
CREDIT_HOLD = re.compile(r"\bcredit hold\b", re.IGNORECASE)
TIER = re.compile(r"\btier\s*([1-3])\b", re.IGNORECASE)

#: Simulated per-call spend, so the leaderboard's cost column is meaningful.
#: More agents means more calls means more money — the trade the study's
#: `debate_critic` architecture makes, and never quantified.
COST_PER_CALL_USD = 0.0009
LATENCY_PER_CALL_MS = 220.0

#: How far into a ticket a fact can sit and still survive summarisation. Past
#: this the worker's free-text summary drops it — the deterministic stand-in
#: for "the summary happened not to mention it".
SALIENCE_WINDOW = 90


def _lookup(ticket: str) -> dict:
    """Stage one: read the account. Sees everything in the ticket."""
    return {
        "tier": (TIER.search(ticket).group(1) if TIER.search(ticket) else "1"),
        "credit_hold": bool(CREDIT_HOLD.search(ticket)),
    }


def _decide(account: dict) -> str:
    """Stage two: apply the escalation policy to whatever it was handed."""
    if account.get("credit_hold"):
        return "on_hold"
    return f"escalate_tier_{account.get('tier', '1')}"


def _result(output: str, calls: int, **metrics) -> dict:
    """The shape a target returns: the answer, plus what it really cost."""
    time.sleep(0.001)  # stand-in for real work, keeps latency non-zero
    return {
        "output": output,
        "cost_usd": COST_PER_CALL_USD * calls,
        "latency_ms": LATENCY_PER_CALL_MS * calls,
        "metrics": {"agent_calls": float(calls), **metrics},
    }


# ---------------------------------------------------------------------------
# the three architectures
# ---------------------------------------------------------------------------


def single_agent(prompt: str) -> dict:
    """One stage, holding the whole ticket. The control.

    Deliberately the fair baseline the study insisted on: it gets unrestricted
    access to the input, so a multi-agent loss cannot be dismissed as a rigged
    comparison.
    """
    return _result(_decide(_lookup(prompt)), calls=1)


def peer_to_peer(prompt: str) -> dict:
    """Two stages joined by a fixed-format handoff string.

    The handoff carries customer, tier and status — and has **no field for
    `credit_hold`**. Stage two is not confused; it never receives the fact. This
    is the exact shape of the study's 0% result, and no better model fixes it,
    because the information is gone before the model is asked anything.
    """
    account = _lookup(prompt)
    handoff = f"HANDOFF: tier={account['tier']}, status=open"  # the lossy boundary

    received = {"tier": handoff.split("tier=")[1].split(",")[0]}
    return _result(_decide(received), calls=2, handoff_fields=2.0)


def supervisor_worker(prompt: str) -> dict:
    """A worker summarises in free text; the supervisor decides from the summary.

    Lossy in a different way: the summary *can* carry the flag, so it fails
    intermittently rather than always. Here that is modelled deterministically
    on salience — a summariser keeps what is prominent and drops what is buried
    late in a long ticket.

    Intermittent is the worse failure to debug. The study measured 71% here
    against a clean 0% for `peer_to_peer`, and a 71% architecture reads like a
    prompt problem right up until you discover it is a structural one.
    """
    account = _lookup(prompt)

    summary = f"Customer is tier {account['tier']}."
    match = CREDIT_HOLD.search(prompt)
    if match and match.start() <= SALIENCE_WINDOW:
        summary += " Account is on credit hold."

    received = {
        "tier": account["tier"],
        "credit_hold": "credit hold" in summary.lower(),
    }
    return _result(_decide(received), calls=3, summary_chars=float(len(summary)))
