"""The evaluation engine.

``ArenaRunner`` walks the model × test-case × trial matrix, scores every
output, and hands the results to the metrics layer. It contains no
project-specific logic whatsoever — everything it does is decided by the
:class:`~agent_arena.core.config.ProjectConfig` it was given.
"""

from __future__ import annotations

import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from ..connectors.base import GenerationRequest
from ..connectors.pricing import PriceBook, build_price_book
from ..connectors.registry import build_connector, requires_api_key, resolve_provider
from ..scorers.base import ScoringContext
from ..scorers.registry import ScorerRegistry, build_registry
from .config import ModelSpec, ProjectConfig, load_config
from .errors import ArenaError, ConfigError, ScorerError
from .hooks import HookSet
from .metrics import Leaderboard, build_leaderboard
from .store import ResultStore
from .testcase import TestCase, load_test_cases

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass
class CallResult:
    """One model's answer to one test case on one trial, graded."""

    model_key: str
    model: str
    test_id: str
    trial: int = 1
    provider: str = ""
    eval_type: str = ""
    status: str = "ok"  # ok | error | skipped
    score: float | None = None
    passed: bool | None = None
    output: str = ""
    reference: Any = None
    reason: str = ""
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    attempts: int = 1
    error: str | None = None
    tags: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_key": self.model_key,
            "model": self.model,
            "provider": self.provider,
            "test_id": self.test_id,
            "trial": self.trial,
            "eval_type": self.eval_type,
            "status": self.status,
            "score": self.score,
            "passed": self.passed,
            "output": self.output,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "attempts": self.attempts,
            "error": self.error,
            "tags": list(self.tags),
            "metrics": dict(self.metrics),
        }


@dataclass
class RunResult:
    """Everything one sweep produced."""

    run_id: str
    project: str
    config: ProjectConfig
    test_cases: list[TestCase]
    results: list[CallResult]
    leaderboard: Leaderboard
    started_at: float = 0.0
    duration_s: float = 0.0
    skipped_models: dict[str, str] = field(default_factory=dict)

    @property
    def winner(self):
        return self.leaderboard.winner

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd or 0.0 for r in self.results)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.status != "ok")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "duration_s": round(self.duration_s, 2),
            "n_models": len(self.config.enabled_models),
            "n_tests": len(self.test_cases),
            "n_results": len(self.results),
            "errors": self.error_count,
            "total_cost_usd": self.total_cost_usd,
            "skipped_models": dict(self.skipped_models),
            "leaderboard": self.leaderboard.to_dict(),
            "results": [r.to_dict() for r in self.results],
        }


class ArenaRunner:
    """Runs one project's evaluation."""

    def __init__(
        self,
        config: ProjectConfig,
        test_cases: Sequence[TestCase] | None = None,
        registry: ScorerRegistry | None = None,
        price_book: PriceBook | None = None,
        hooks: HookSet | None = None,
        store: ResultStore | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or build_registry(config)
        self.price_book = price_book or build_price_book(config)
        self.hooks = hooks or HookSet.load(config.hooks, base_dir=config.root)
        self.progress = progress
        self._store = store
        self._owns_store = store is None
        self._judge_connector = None
        self._judge_lock = threading.Lock()

        if test_cases is None:
            test_cases = load_test_cases(
                config.discover_test_files(),
                default_eval_type=config.default_eval_type,
                test_filter=config.test_filter,
            )
        self.test_cases = list(test_cases)

    # ---- construction -------------------------------------------------

    @classmethod
    def from_project(
        cls,
        project_path: str | Path,
        progress: ProgressCallback | None = None,
        **overrides: Any,
    ) -> ArenaRunner:
        config = load_config(project_path, **overrides)
        return cls(config, progress=progress)

    @property
    def store(self) -> ResultStore:
        if self._store is None:
            self._store = ResultStore(self.config.database)
        return self._store

    # ---- preflight ----------------------------------------------------

    def preflight(self) -> dict[str, str]:
        """Validate everything we can before spending a cent.

        Returns a mapping of ``model_key -> reason`` for models that will be
        skipped (missing credentials). Raises on anything the user must fix.
        """
        if not self.test_cases:
            raise ConfigError("no test cases to run")
        if not self.config.enabled_models:
            raise ConfigError("no enabled models to run")

        missing_reference: list[str] = []
        for case in self.test_cases:
            # Also warms the registry's cache on the main thread, so the worker
            # pool never races to construct the same scorer.
            scorer = self.registry.get(case.eval_type)  # raises on unknown eval_type
            if scorer.requires_reference and not case.has_reference:
                missing_reference.append(f"{case.id} ({case.eval_type})")
        if missing_reference:
            raise ConfigError(
                "these test cases need a 'reference' for their eval_type: "
                + ", ".join(missing_reference[:10])
                + ("…" if len(missing_reference) > 10 else "")
            )

        needs_judge = any(
            self.registry.get(c.eval_type).name == "llm_judge" for c in self.test_cases
        )
        if needs_judge and not self.config.judge.get("model"):
            raise ConfigError(
                "some test cases use eval_type: llm_judge but no judge is configured. Add:\n"
                "  judge:\n    model: claude-opus-5"
            )

        skipped: dict[str, str] = {}
        for spec in self.config.enabled_models:
            env_var = requires_api_key(spec)
            if env_var and not self.config.env_for(spec):
                import os  # noqa: PLC0415

                if not os.environ.get(env_var):
                    skipped[spec.key] = f"{env_var} is not set"
                    continue

            # A local server that is not running is the same class of problem
            # as a missing API key: skip it with a reason instead of emitting
            # one connection error per test case.
            if resolve_provider(spec) in ("local", "ollama", "lmstudio"):
                connector = self._connector_for(spec)
                try:
                    reason = connector.healthcheck()
                finally:
                    connector.close()
                if reason:
                    skipped[spec.key] = reason
        return skipped

    # ---- execution ----------------------------------------------------

    def run(self, dry_run: bool = False) -> RunResult:
        started = time.perf_counter()
        skipped = self.preflight()

        runnable = [s for s in self.config.enabled_models if s.key not in skipped]
        if not runnable:
            detail = "; ".join(f"{key} ({reason})" for key, reason in skipped.items())
            raise ConfigError(
                f"every model would be skipped, so there is nothing to run: {detail}.\n"
                "Export the missing API key(s), or add a `mock:` model to compare against."
            )
        planned = len(runnable) * len(self.test_cases) * self.config.run.trials

        self._emit(
            "run_start",
            models=[s.key for s in runnable],
            skipped=skipped,
            tests=len(self.test_cases),
            trials=self.config.run.trials,
            planned=planned,
        )

        if dry_run:
            leaderboard = build_leaderboard(
                self.config, {}, self.config.enabled_models, self.price_book
            )
            return RunResult(
                run_id="dry-run",
                project=self.config.project,
                config=self.config,
                test_cases=self.test_cases,
                results=[],
                leaderboard=leaderboard,
                started_at=started,
                duration_s=0.0,
                skipped_models=skipped,
            )

        run_id = self.store.start_run(
            self.config.project,
            models=[s.key for s in runnable],
            n_tests=len(self.test_cases),
            weights=self.config.metrics.normalized_weights(),
            config_snapshot=self.config.raw,
            arena_version=_arena_version(),
            git_sha=_git_sha(self.config.root),
        )

        connectors = {spec.key: self._connector_for(spec) for spec in runnable}
        results: list[CallResult] = []
        completed = 0

        try:
            jobs = [
                (spec, case, trial)
                for spec in runnable
                for case in self.test_cases
                for trial in range(1, self.config.run.trials + 1)
            ]
            with ThreadPoolExecutor(max_workers=self.config.run.concurrency) as pool:
                futures = {
                    pool.submit(self._execute, connectors[spec.key], spec, case, trial): (
                        spec,
                        case,
                        trial,
                    )
                    for spec, case, trial in jobs
                }
                for future in as_completed(futures):
                    spec, case, trial = futures[future]
                    try:
                        result = future.result()
                    except ArenaError:
                        raise
                    except Exception as exc:  # noqa: BLE001 — recorded, not fatal
                        result = CallResult(
                            model_key=spec.key,
                            model=spec.model,
                            test_id=case.id,
                            trial=trial,
                            eval_type=case.eval_type,
                            status="error",
                            error=f"{type(exc).__name__}: {exc}",
                            reference=case.reference,
                            tags=list(case.tags),
                        )
                    results.append(result)
                    self.store.record_result(run_id, self.config.project, result)
                    completed += 1
                    self._emit(
                        "call_complete",
                        completed=completed,
                        planned=planned,
                        result=result,
                    )
                    if result.status != "ok" and self.config.run.fail_fast:
                        raise ArenaError(
                            f"stopping: {spec.key} failed on {case.id} — {result.error} "
                            "(run.fail_fast is on)"
                        )
        finally:
            for connector in connectors.values():
                connector.close()

        results.sort(key=lambda r: (r.model_key, r.test_id, r.trial))

        by_model: dict[str, list[CallResult]] = {spec.key: [] for spec in self.config.enabled_models}
        for result in results:
            by_model.setdefault(result.model_key, []).append(result)

        leaderboard = build_leaderboard(
            self.config,
            by_model,
            self.config.enabled_models,
            self.price_book,
            weights_by_test={c.id: c.weight for c in self.test_cases},
        )
        for key, reason in skipped.items():
            entry = leaderboard.get(key)
            if entry:
                entry.status = "no_data"
                # Replace rather than append: "no results recorded" is a
                # consequence of the skip, not a second problem.
                entry.failures = [f"skipped — {reason}"]

        duration = time.perf_counter() - started
        total_cost = sum(r.cost_usd or 0.0 for r in results)
        self.store.finish_run(
            run_id,
            self.config.project,
            leaderboard,
            n_results=len(results),
            total_cost_usd=total_cost,
        )
        if self._owns_store:
            self.store.close()
            self._store = None

        run_result = RunResult(
            run_id=run_id,
            project=self.config.project,
            config=self.config,
            test_cases=self.test_cases,
            results=results,
            leaderboard=leaderboard,
            started_at=started,
            duration_s=duration,
            skipped_models=skipped,
        )
        self._emit("run_complete", result=run_result)
        return run_result

    # ---- one call -----------------------------------------------------

    def _execute(self, connector: Any, spec: ModelSpec, case: TestCase, trial: int) -> CallResult:
        result = CallResult(
            model_key=spec.key,
            model=spec.model,
            provider=connector.provider,
            test_id=case.id,
            trial=trial,
            eval_type=case.eval_type,
            reference=case.reference,
            tags=list(case.tags),
        )

        defaults = self.config.defaults
        request = GenerationRequest(
            messages=case.messages,
            system=case.context or defaults.get("system"),
            max_tokens=case.max_tokens or defaults.get("max_tokens"),
            temperature=(
                case.temperature if case.temperature is not None else defaults.get("temperature")
            ),
            params=dict(spec.params),
            metadata={
                "test_id": case.id,
                "trial": trial,
                "model_key": spec.key,
                "reference": case.reference,
            },
        )
        request = self.hooks.apply_pre_request(request, case, spec.key)

        generation, error, attempts = self._generate_with_retries(connector, request)
        result.attempts = attempts

        if generation is None:
            result.status = "error"
            result.error = error
            return result

        result.output = generation.text
        result.latency_ms = generation.latency_ms
        result.input_tokens = generation.input_tokens
        result.output_tokens = generation.output_tokens
        card = self.price_book.get(spec.model, provider=connector.provider)
        result.cost_usd = card.cost_usd(
            generation.input_tokens,
            generation.output_tokens,
            generation.cache_read_tokens,
            generation.cache_write_tokens,
        )

        context = ScoringContext(
            test_case=case,
            model_key=spec.key,
            options=self.config.scorer_options.get(case.eval_type, {}),
            judge=self._judge,
            project_root=self.config.root,
        )

        outcome = self.hooks.apply_post_process(result.output, case, context)
        result.output = outcome.output
        result.metrics.update(outcome.metrics)
        result.detail.update(outcome.detail)

        if outcome.overrides_verdict:
            result.score = outcome.score if outcome.score is not None else float(bool(outcome.passed))
            result.passed = outcome.passed if outcome.passed is not None else result.score >= 0.5
            result.reason = outcome.reason or "set by post_process hook"
            self.hooks.apply_on_result(result)
            return result

        scorer = self.registry.get(case.eval_type)
        try:
            verdict = scorer(result.output, case.reference, context)
        except ScorerError:
            raise
        except Exception as exc:  # noqa: BLE001 — a broken scorer fails its call, not the run
            result.status = "error"
            result.error = f"scorer {case.eval_type!r} raised {type(exc).__name__}: {exc}"
            return result

        result.score = verdict.score
        result.passed = verdict.passed
        result.reason = verdict.reason
        result.metrics.update(verdict.metrics)
        result.detail.update(verdict.detail)
        self.hooks.apply_on_result(result)
        return result

    def _generate_with_retries(self, connector: Any, request: GenerationRequest):
        last_error = ""
        attempts = 0
        for attempt in range(self.config.run.retries + 1):
            attempts = attempt + 1
            try:
                return connector.generate(request), None, attempts
            except Exception as exc:  # noqa: BLE001 — provider errors are data here
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.config.run.retries:
                    time.sleep(self.config.run.retry_backoff_s * (2**attempt))
        return None, last_error, attempts

    # ---- collaborators ------------------------------------------------

    def _connector_for(self, spec: ModelSpec):
        connector = build_connector(spec, self.config.defaults)
        connector.timeout_s = self.config.run.timeout_s
        return connector

    def _judge(self, prompt: str, system: str | None = None) -> str:
        """Callable handed to LLM-judge scorers. Called from worker threads."""
        with self._judge_lock:
            if self._judge_connector is None:
                judge_config = self.config.judge
                model = judge_config.get("model")
                if not model:
                    raise ConfigError("no judge model configured (judge.model)")
                spec = ModelSpec(
                    key="__judge__",
                    model=str(model),
                    provider=judge_config.get("provider"),
                    params=dict(judge_config.get("params") or {}),
                    api_key_env=judge_config.get("api_key_env"),
                    api_base=judge_config.get("api_base"),
                )
                connector = build_connector(spec)
                connector.timeout_s = self.config.run.timeout_s
                self._judge_connector = connector

        request = GenerationRequest(
            messages=[{"role": "user", "content": prompt}],
            system=system or self.config.judge.get("system"),
            max_tokens=int(self.config.judge.get("max_tokens", 512)),
            temperature=self.config.judge.get("temperature"),
            metadata={"role": "judge"},
        )
        return self._judge_connector.generate(request).text

    def _emit(self, event: str, **payload: Any) -> None:
        if self.progress:
            self.progress({"event": event, **payload})


def _arena_version() -> str:
    from .. import __version__  # noqa: PLC0415 — avoids a circular import at module load

    return __version__


def _git_sha(cwd: Path) -> str:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(cwd),
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
