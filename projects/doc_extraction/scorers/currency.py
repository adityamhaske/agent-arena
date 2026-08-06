"""A scorer only this project could write.

ISO currency codes come back in half a dozen shapes — `GBP`, `gbp`, `£`,
`"pound sterling"`, or wrapped in JSON. None of the built-in scorers should
know that, so the knowledge lives here, next to the project that needs it.
"""

from agent_arena.scorers import Scorer, ScoreResult, extract_json

SYMBOLS = {
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
    "¥": "JPY",
    "pound": "GBP",
    "pounds": "GBP",
    "sterling": "GBP",
    "dollar": "USD",
    "dollars": "USD",
    "euro": "EUR",
    "euros": "EUR",
    "yen": "JPY",
}


class IsoCurrencyScorer(Scorer):
    """Compare currencies after normalising symbols and names to ISO codes."""

    name = "iso_currency"
    description = "Normalises £/$/€/'pounds' to ISO 4217 before comparing."

    def score(self, output, reference, context):
        expected = normalise(str(reference))
        actual = normalise(self._extract(output))
        ok = actual is not None and actual == expected
        return ScoreResult(
            score=1.0 if ok else 0.0,
            passed=ok,
            reason="" if ok else f"read {actual or '(nothing)'}, expected {expected}",
            detail={"normalised": actual},
        )

    @staticmethod
    def _extract(output: str) -> str:
        parsed = extract_json(output)
        if isinstance(parsed, dict):
            for key in ("currency", "currency_code", "iso_currency"):
                if key in parsed:
                    return str(parsed[key])
        return str(output)


def normalise(value: str) -> str | None:
    """Map a symbol, name or code onto an ISO 4217 code."""
    text = (value or "").strip()
    if not text:
        return None
    for symbol, code in SYMBOLS.items():
        if symbol in text.lower():
            return code
    letters = "".join(ch for ch in text.upper() if ch.isalpha())
    return letters[:3] if len(letters) >= 3 else None
