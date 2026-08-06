"""Scorers that ship with the arena.

These cover the shapes most projects need out of the box. Anything more
specific belongs in a project-local ``scorers/`` folder — see
:mod:`agent_arena.scorers.base`.
"""

from __future__ import annotations

import json
import math
import re
import string
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..core.errors import ScorerError
from ..core.loaders import load_python_object
from .base import Scorer, ScoreResult, ScoringContext

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)
_CODE_FENCE = re.compile(r"```(?:[\w+-]*)\n(.*?)```", re.DOTALL)
_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?")


def normalize_text(
    text: Any,
    *,
    case_sensitive: bool = False,
    strip_punctuation: bool = True,
    collapse_whitespace: bool = True,
) -> str:
    value = "" if text is None else str(text)
    value = value.strip()
    if not case_sensitive:
        value = value.lower()
    if strip_punctuation:
        value = value.translate(_PUNCT_TABLE)
    if collapse_whitespace:
        value = " ".join(value.split())
    return value


class ExactMatchScorer(Scorer):
    """Output must equal the reference after normalisation."""

    name = "exact_match"
    description = "Normalised string equality (case/punctuation/whitespace insensitive by default)."

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        params = context.params
        norm = dict(
            case_sensitive=bool(params.get("case_sensitive", False)),
            strip_punctuation=bool(params.get("strip_punctuation", True)),
            collapse_whitespace=bool(params.get("collapse_whitespace", True)),
        )
        got = normalize_text(output, **norm)

        # A list reference means "any of these is correct".
        candidates = reference if isinstance(reference, (list, tuple)) else [reference]
        expected = [normalize_text(c, **norm) for c in candidates]

        matched = got in expected
        return ScoreResult(
            score=1.0 if matched else 0.0,
            passed=matched,
            reason="" if matched else f"expected {expected[0]!r}, got {got!r}",
            detail={"normalized_output": got, "normalized_reference": expected},
        )


class ContainsScorer(Scorer):
    """Output must contain the reference text (or every item of a list)."""

    name = "contains"
    description = "Substring containment; a list reference requires all/any depending on `mode`."

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        params = context.params
        case_sensitive = bool(params.get("case_sensitive", False))
        mode = str(params.get("mode", "all")).lower()

        haystack = output if case_sensitive else output.lower()
        needles = reference if isinstance(reference, (list, tuple)) else [reference]
        needles = [str(n) if case_sensitive else str(n).lower() for n in needles]

        hits = [n for n in needles if n in haystack]
        if mode == "any":
            score = 1.0 if hits else 0.0
        else:
            score = len(hits) / len(needles) if needles else 0.0

        threshold = float(params.get("threshold", 1.0))
        return ScoreResult(
            score=score,
            passed=score >= threshold,
            reason="" if score >= threshold else f"missing: {sorted(set(needles) - set(hits))}",
            detail={"matched": hits, "expected": needles, "mode": mode},
        )


class RegexScorer(Scorer):
    """The reference is a regular expression that must match the output."""

    name = "regex"
    description = "Regex search over the output; optional capture-group comparison."

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        params = context.params
        flags = 0 if params.get("case_sensitive", False) else re.IGNORECASE
        if params.get("multiline", False):
            flags |= re.MULTILINE | re.DOTALL

        pattern = params.get("pattern", reference)
        try:
            compiled = re.compile(str(pattern), flags)
        except re.error as exc:
            raise ScorerError(f"invalid regex {pattern!r}: {exc}") from exc

        match = compiled.search(output or "")
        if not match:
            return ScoreResult(score=0.0, passed=False, reason=f"no match for /{pattern}/")

        expected_group = params.get("expect_group")
        if expected_group is not None:
            captured = match.group(1) if match.groups() else match.group(0)
            ok = normalize_text(captured) == normalize_text(expected_group)
            return ScoreResult(
                score=1.0 if ok else 0.0,
                passed=ok,
                reason="" if ok else f"captured {captured!r}, expected {expected_group!r}",
                detail={"captured": captured},
            )
        return ScoreResult(score=1.0, passed=True, detail={"matched": match.group(0)})


class ClassificationScorer(Scorer):
    """Pick the label the output names, out of a fixed set."""

    name = "classification"
    description = "Finds which of `labels` the output selects, then compares to the reference."

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        params = context.params
        labels = params.get("labels")
        if not labels:
            raise ScorerError(
                "classification scorer needs a 'labels' list, either in the test case's "
                "params or in scorers.options.classification.labels"
            )
        normalized_output = normalize_text(output)
        # Longest first so "not_spam" is not swallowed by "spam".
        found = [
            label
            for label in sorted(labels, key=lambda x: len(str(x)), reverse=True)
            if re.search(rf"\b{re.escape(normalize_text(label))}\b", normalized_output)
        ]
        predicted = found[0] if found else None
        # A list reference means several labels are acceptable for this case.
        accepted = reference if isinstance(reference, (list, tuple)) else [reference]
        expected = {normalize_text(r) for r in accepted}
        ok = predicted is not None and normalize_text(predicted) in expected

        if predicted is None:
            reason = f"output named none of the labels {list(labels)}"
        elif not ok:
            reason = f"predicted {predicted!r}, expected one of {list(accepted)!r}"
        else:
            reason = ""
        return ScoreResult(
            score=1.0 if ok else 0.0,
            passed=ok,
            reason=reason,
            detail={"predicted": predicted, "candidates": found},
        )


class NumericScorer(Scorer):
    """Compare the number in the output to the reference within a tolerance."""

    name = "numeric"
    description = "Extracts a number from the output and compares with abs/rel tolerance."

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        params = context.params
        try:
            expected = float(reference)
        except (TypeError, ValueError) as exc:
            raise ScorerError(f"numeric scorer needs a numeric reference, got {reference!r}") from exc

        matches = _NUMBER.findall(output or "")
        if not matches:
            return ScoreResult(score=0.0, passed=False, reason="no number found in output")

        which = str(params.get("select", "last")).lower()
        raw = matches[-1] if which == "last" else matches[0]
        try:
            actual = float(raw.replace(",", ""))
        except ValueError:
            return ScoreResult(score=0.0, passed=False, reason=f"unparseable number {raw!r}")

        abs_tol = float(params.get("abs_tol", params.get("tolerance", 0.0)))
        rel_tol = float(params.get("rel_tol", 0.0))
        ok = math.isclose(actual, expected, abs_tol=abs_tol, rel_tol=rel_tol)
        return ScoreResult(
            score=1.0 if ok else 0.0,
            passed=ok,
            reason="" if ok else f"got {actual}, expected {expected} (abs_tol={abs_tol})",
            detail={"actual": actual, "expected": expected},
            metrics={"abs_error": abs(actual - expected)},
        )


class JsonMatchScorer(Scorer):
    """Parse the output as JSON and compare it with the reference structure."""

    name = "json_match"
    description = "JSON-parses the output; scores the fraction of reference keys that match."

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        params = context.params
        parsed = extract_json(output)
        if parsed is None:
            return ScoreResult(score=0.0, passed=False, reason="output is not valid JSON")

        expected = reference
        if isinstance(expected, str):
            expected = extract_json(expected)
            if expected is None:
                raise ScorerError("json_match reference is a string but not valid JSON")

        mode = str(params.get("mode", "subset")).lower()
        if mode == "exact":
            ok = parsed == expected
            return ScoreResult(
                score=1.0 if ok else 0.0,
                passed=ok,
                reason="" if ok else "JSON differs from reference",
                detail={"parsed": parsed},
            )

        if not isinstance(expected, dict) or not isinstance(parsed, dict):
            ok = parsed == expected
            return ScoreResult(score=1.0 if ok else 0.0, passed=ok, detail={"parsed": parsed})

        ignore = {str(k) for k in params.get("ignore_keys", [])}
        keys = [k for k in expected if k not in ignore]
        if not keys:
            return ScoreResult(score=1.0, passed=True, detail={"parsed": parsed})

        matches = {k: _loose_equal(parsed.get(k), expected[k]) for k in keys}
        score = sum(matches.values()) / len(keys)
        threshold = float(params.get("threshold", 1.0))
        missing = [k for k, ok in matches.items() if not ok]
        return ScoreResult(
            score=score,
            passed=score >= threshold,
            reason="" if score >= threshold else f"mismatched keys: {missing}",
            detail={"parsed": parsed, "mismatched": missing},
        )


class SemanticSimilarityScorer(Scorer):
    """Similarity between output and reference, above a threshold.

    By default this is a **lexical** proxy (token-set cosine over content
    words), which needs no model and no network — good enough to catch
    paraphrase-level equivalence on short answers, and honest about being
    shallow. Point ``embedding`` at your own function for real embeddings::

        scorers:
          options:
            semantic:
              embedding: "scorers/embed.py:embed"   # (text) -> list[float]
              threshold: 0.82
    """

    name = "semantic"
    description = "Token-set cosine similarity, or your own embedding function."

    _STOPWORDS = {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has",
        "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to",
        "was", "were", "will", "with",
    }

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        params = context.params
        threshold = float(params.get("threshold", 0.75))
        embedding_spec = params.get("embedding")

        if embedding_spec:
            embed = load_python_object(str(embedding_spec), base_dir=context.project_root)
            similarity = _cosine(embed(output or ""), embed(str(reference)))
            method = "embedding"
        else:
            similarity = self._lexical_similarity(output or "", str(reference))
            method = "lexical"

        return ScoreResult(
            score=similarity,
            passed=similarity >= threshold,
            reason="" if similarity >= threshold else f"similarity {similarity:.2f} < {threshold}",
            detail={"similarity": round(similarity, 4), "method": method},
            metrics={"similarity": similarity},
        )

    def _tokens(self, text: str) -> set[str]:
        words = normalize_text(text).split()
        content = {w for w in words if w not in self._STOPWORDS}
        return content or set(words)

    def _lexical_similarity(self, a: str, b: str) -> float:
        ta, tb = self._tokens(a), self._tokens(b)
        if not ta or not tb:
            return 0.0
        overlap = len(ta & tb)
        return overlap / math.sqrt(len(ta) * len(tb))


DEFAULT_JUDGE_PROMPT = """You are grading one answer produced by an AI model.

<task>
{input}
</task>

<reference_answer>
{reference}
</reference_answer>

<model_answer>
{output}
</model_answer>

<rubric>
{rubric}
</rubric>

Grade the model answer. Reply with JSON only, no prose:
{{"score": <number between 0 and 1>, "passed": <true or false>, "reason": "<one short sentence>"}}"""

DEFAULT_RUBRIC = (
    "Award 1.0 when the model answer is factually consistent with the reference and "
    "fully addresses the task; award partial credit when it is partially correct; "
    "award 0.0 when it is wrong, empty, or contradicts the reference. Differences in "
    "wording, format, or verbosity do not matter."
)


class LLMJudgeScorer(Scorer):
    """Ask a model to grade the output against the reference and a rubric."""

    name = "llm_judge"
    requires_reference = False
    description = "Grades with a judge model; returns its 0-1 score."

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        if context.judge is None:
            raise ScorerError(
                "llm_judge needs a judge model. Add one to the project config:\n"
                "  judge:\n    model: claude-opus-5"
            )
        params = context.params
        template = str(params.get("prompt", DEFAULT_JUDGE_PROMPT))
        rubric = str(params.get("rubric", DEFAULT_RUBRIC))
        threshold = float(params.get("threshold", 0.5))

        test_input = getattr(context.test_case, "input", "")
        prompt = template.format(
            input=test_input,
            reference="(no reference provided)" if reference is None else reference,
            output=output,
            rubric=rubric,
        )
        verdict = context.judge(prompt, system=params.get("system"))
        parsed = extract_json(verdict) or {}

        if isinstance(parsed, dict) and "score" in parsed:
            try:
                score = float(parsed["score"])
            except (TypeError, ValueError) as exc:
                raise ScorerError(f"judge returned a non-numeric score: {parsed['score']!r}") from exc
            reason = str(parsed.get("reason", ""))
            passed = bool(parsed.get("passed", score >= threshold))
        else:
            score, reason, passed = self._parse_loose(verdict, threshold)

        return ScoreResult(
            score=score,
            passed=passed,
            reason=reason,
            detail={"judge_raw": verdict[:2000]},
        )

    @staticmethod
    def _parse_loose(verdict: str, threshold: float) -> tuple[float, str, bool]:
        text = (verdict or "").strip()
        upper = text.upper()
        if "PASS" in upper and "FAIL" not in upper:
            return 1.0, text[:200], True
        if "FAIL" in upper:
            return 0.0, text[:200], False
        numbers = _NUMBER.findall(text)
        if numbers:
            value = float(numbers[0])
            if value > 1:  # judge answered on a 0-10 or 0-100 scale
                value = value / 10.0 if value <= 10 else value / 100.0
            value = max(0.0, min(1.0, value))
            return value, text[:200], value >= threshold
        raise ScorerError(f"could not parse a score from the judge's reply: {text[:200]!r}")


class CodeExecScorer(Scorer):
    """Run the code the model produced against the project's assertions.

    .. warning::
       This executes model-generated code in a subprocess on this machine. It
       applies a timeout and a scratch working directory, but it is **not** a
       sandbox — run untrusted outputs in a container.
    """

    name = "code_exec"
    requires_reference = False
    description = "Executes generated code plus reference assertions in a subprocess."

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        params = context.params
        language = str(params.get("language", "python")).lower()
        if language != "python":
            raise ScorerError(
                f"code_exec currently supports python only, got {language!r}; "
                "write a project-local scorer for other languages"
            )

        timeout = float(params.get("timeout_s", 15.0))
        setup = str(params.get("setup", ""))
        checks = params.get("tests")
        if checks is None:
            checks = reference
        if checks is None:
            raise ScorerError(
                "code_exec needs assertions — put them in the test case's `reference` "
                "or in params.tests"
            )
        if isinstance(checks, (list, tuple)):
            checks = "\n".join(str(c) for c in checks)

        code = extract_code(output, params.get("fence_language"))
        program = "\n\n".join(part for part in (setup, code, str(checks)) if part.strip())

        with tempfile.TemporaryDirectory(prefix="arena-code-") as tmpdir:
            script = Path(tmpdir) / "candidate.py"
            script.write_text(program, encoding="utf-8")
            try:
                proc = subprocess.run(  # noqa: S603 - documented, timeout-bounded
                    [sys.executable, str(script)],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=tmpdir,
                )
            except subprocess.TimeoutExpired:
                return ScoreResult(
                    score=0.0,
                    passed=False,
                    reason=f"execution exceeded {timeout}s",
                    detail={"timeout": True},
                )

        ok = proc.returncode == 0
        return ScoreResult(
            score=1.0 if ok else 0.0,
            passed=ok,
            reason="" if ok else _last_line(proc.stderr) or f"exit code {proc.returncode}",
            detail={
                "returncode": proc.returncode,
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-2000:],
            },
        )


class ManualScorer(Scorer):
    """Record the output for human review without scoring it."""

    name = "manual"
    requires_reference = False
    description = "Always returns 0.5/unscored — use to collect outputs for human grading."

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        return ScoreResult(
            score=0.5,
            passed=None,
            reason="awaiting human review",
            detail={"output": output[:2000]},
        )


# ---------------------------------------------------------------------------
# helpers shared by several scorers
# ---------------------------------------------------------------------------


def extract_json(text: str) -> Any | None:
    """Best-effort JSON extraction from a model reply (handles fences and prose)."""
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text

    candidates = [str(text).strip()]
    fenced = _CODE_FENCE.findall(str(text))
    candidates = fenced + candidates

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        # Fall back to the outermost {...} or [...] span.
        for opener, closer in (("{", "}"), ("[", "]")):
            start, end = candidate.find(opener), candidate.rfind(closer)
            if 0 <= start < end:
                try:
                    return json.loads(candidate[start : end + 1])
                except json.JSONDecodeError:
                    continue
    return None


def extract_code(text: str, language: str | None = None) -> str:
    """Pull code out of a fenced block, or return the text unchanged."""
    if not text:
        return ""
    if language:
        pattern = re.compile(rf"```{re.escape(language)}\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
        specific = pattern.findall(text)
        if specific:
            return "\n\n".join(block.strip() for block in specific)
    blocks = _CODE_FENCE.findall(text)
    if blocks:
        return "\n\n".join(block.strip() for block in blocks)
    return text.strip()


def _loose_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return normalize_text(actual) == normalize_text(expected)
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=1e-9)
    return actual == expected


def _cosine(a: Any, b: Any) -> float:
    va, vb = list(a), list(b)
    if len(va) != len(vb) or not va:
        raise ScorerError("embedding function returned vectors of different or zero length")
    dot = sum(x * y for x, y in zip(va, vb))
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(y * y for y in vb))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def _last_line(text: str) -> str:
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


BUILTIN_SCORERS: dict[str, type[Scorer]] = {
    cls.name: cls
    for cls in (
        ExactMatchScorer,
        ContainsScorer,
        RegexScorer,
        ClassificationScorer,
        NumericScorer,
        JsonMatchScorer,
        SemanticSimilarityScorer,
        LLMJudgeScorer,
        CodeExecScorer,
        ManualScorer,
    )
}
