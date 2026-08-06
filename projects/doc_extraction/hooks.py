"""Normalise model output before it is graded.

Models that are otherwise correct routinely wrap JSON in a markdown fence or a
sentence of preamble. That is a formatting difference, not an extraction
error, and grading it as a failure would rank models on their chattiness
rather than on whether they read the invoice correctly. Strip it once here,
rather than teaching every scorer about fences.
"""

import re

FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
BANK_ACCOUNT = re.compile(r"\b(\d{4})\d{2,}(\d{2})\b")


def post_process(output, test_case, context):
    """Return the cleaned-up output, plus a metric tracking how often we had to."""
    cleaned = output.strip()

    fenced = FENCE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()

    # Drop any preamble before the first JSON object on multi-line answers.
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        if start > 0 and cleaned.rstrip().endswith("}"):
            cleaned = cleaned[start:].strip()

    return {
        "output": cleaned,
        # Custom metrics can be weighted in config exactly like accuracy.
        "metrics": {"needed_cleanup": 1.0 if cleaned != output.strip() else 0.0},
    }
