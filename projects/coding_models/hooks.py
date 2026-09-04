"""Shape a model's reply into something `code_exec` can run.

Models wrap code in a markdown fence even when the prompt says not to. That is
a formatting habit, not a wrong answer, and grading it as a failure would tell
you the model cannot code when it can. Stripping the fence here keeps the
scorer measuring the thing you actually care about.
"""

from __future__ import annotations


def post_process(output: str, case, context):
    """Return just the code from a reply that may be wrapped in a fence."""
    text = (output or "").strip()
    if "```" not in text:
        return text

    # Take the first fenced block; a reply with prose around it still works.
    _, _, rest = text.partition("```")
    if rest[:6].lower().startswith("python"):
        rest = rest[6:]
    elif rest[:1] == "\n":
        pass
    body, _, _ = rest.partition("```")
    return body.strip()
