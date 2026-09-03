"""The UI's data layer: plain Python in, plain dicts out.

Deliberately free of HTTP. Every endpoint the browser calls is a method here,
so the whole UI is testable without a socket, and so the rules that matter —
you cannot write outside the projects directory, you cannot start two paid runs
by double-clicking — live somewhere they can be tested rather than in a request
handler.

The engine is never reimplemented. Runs go through :class:`ArenaRunner`;
rankings go through :func:`build_leaderboard`. This module wires them to the
browser and hands the output to :mod:`agent_arena.web.language` for wording.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..connectors.pricing import build_price_book
from ..connectors.registry import requires_api_key, resolve_provider
from ..core.config import BUILTIN_METRICS, ProjectConfig, load_config
from ..core.errors import ArenaError
from ..core.loaders import yaml_available
from ..core.metrics import build_leaderboard
from ..core.runner import ArenaRunner, CallResult
from ..core.store import ResultStore
from ..scorers.registry import ScorerRegistry
from . import language as lang

#: Project folder names are used as path segments and as SQLite `project`
#: values. Anything outside this set is rejected before it reaches the disk.
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: Simulated models, offered first in the wizard. A non-technical user should
#: be able to complete an entire evaluation — and understand what the output
#: means — before being asked for an API key or a credit card.
DEMO_MODELS = [
    {
        "key": "sim_frontier",
        "model": "mock:frontier",
        "label": "Frontier-class (simulated)",
        "params": {"mode": "flaky", "accuracy": 96, "latency_ms": 1500},
        "card": {"input_usd_per_mtok": 5, "output_usd_per_mtok": 25},
        "blurb": "Most accurate, slowest, priciest.",
    },
    {
        "key": "sim_balanced",
        "model": "mock:balanced",
        "label": "Mid-tier (simulated)",
        "params": {"mode": "flaky", "accuracy": 88, "latency_ms": 620},
        "card": {"input_usd_per_mtok": 3, "output_usd_per_mtok": 15},
        "blurb": "A middle option on all three.",
    },
    {
        "key": "sim_small",
        "model": "mock:small",
        "label": "Small/fast (simulated)",
        "params": {"mode": "flaky", "accuracy": 78, "latency_ms": 190},
        "card": {"input_usd_per_mtok": 1, "output_usd_per_mtok": 5},
        "blurb": "Cheap and instant, less accurate.",
    },
    {
        "key": "sim_tiny",
        "model": "mock:tiny",
        "label": "Tiny (simulated)",
        "params": {"mode": "flaky", "accuracy": 55, "latency_ms": 90},
        "card": {"input_usd_per_mtok": 0.25, "output_usd_per_mtok": 1.25},
        "blurb": "Cheapest — usually too inaccurate to use.",
    },
]


class ApiError(ArenaError):
    """A request the UI got wrong. Carries an HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# background runs
# ---------------------------------------------------------------------------


#: A finished job is kept so the browser can still poll it and re-open its
#: results, but `arena ui` is a long-running process: without a cap, every
#: evaluation would leak a Job and its buffered feed for the life of the
#: server. Fifty is far more history than any view shows.
MAX_RETAINED_JOBS = 50

#: A job in one of these states still has a thread behind it, so its id is the
#: only handle the browser has on a run that may be spending money.
LIVE_STATUSES = ("starting", "running")


class Job:
    """One evaluation running in a thread, pollable from the browser."""

    def __init__(self, job_id: str, project: str) -> None:
        self.id = job_id
        self.project = project
        self.status = "starting"  # starting | running | done | error | cancelled
        self.completed = 0
        self.planned = 0
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.skipped: dict[str, str] = {}
        self.error: str | None = None
        self.error_detail: str | None = None
        self.run_id: str | None = None
        self.payload: dict[str, Any] | None = None
        self.recent: list[dict[str, Any]] = []
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Ask the run to stop.

        Cooperative, not a kill: only the loop making the calls can stop
        *spending*, and tearing its thread down mid-write would leave the
        results store half-populated. The flag is an Event so the runner can
        wait on it as well as poll it.
        """
        self.cancel_event.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed = (self.finished_at or time.time()) - self.started_at
            fraction = (self.completed / self.planned) if self.planned else 0.0
            remaining = None
            if self.status == "running" and self.completed > 5 and fraction > 0:
                remaining = max(0.0, elapsed / fraction - elapsed)
            return {
                "id": self.id,
                "project": self.project,
                "status": self.status,
                "completed": self.completed,
                "planned": self.planned,
                "fraction": round(fraction, 4),
                "elapsed_s": round(elapsed, 1),
                "eta_s": round(remaining, 1) if remaining is not None else None,
                "skipped": dict(self.skipped),
                "error": self.error,
                "error_detail": self.error_detail,
                "run_id": self.run_id,
                "recent": list(self.recent),
                "result": self.payload,
                # A cancelled run keeps reporting progress until the runner
                # notices, so the UI needs to know the stop was asked for.
                "cancel_requested": self.cancel_event.is_set(),
            }

    def on_event(self, event: dict[str, Any]) -> None:
        kind = event.get("event")
        with self._lock:
            if kind == "run_start":
                self.status = "running"
                self.planned = event.get("planned", 0)
                self.skipped = dict(event.get("skipped") or {})
            elif kind == "call_complete":
                self.completed = event.get("completed", self.completed)
                self.planned = event.get("planned", self.planned)
                result = event.get("result")
                if result is not None:
                    # A live feed of what the models are actually saying is the
                    # difference between a progress bar and a run you trust.
                    self.recent.append(
                        {
                            "model": result.model_key,
                            "test": result.test_id,
                            "status": result.status,
                            "passed": result.passed,
                            "output": (result.output or "")[:280],
                            "error": result.error,
                        }
                    )
                    del self.recent[:-40]


class JobManager:
    """Every run this process has started, oldest first.

    Insertion order is the retention order: dicts keep it, which is why the
    eviction below needs no timestamps and no background thread.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._by_project: dict[str, str] = {}
        self._lock = threading.Lock()

    def active_for(self, project: str) -> Job | None:
        with self._lock:
            job_id = self._by_project.get(project)
            job = self._jobs.get(job_id) if job_id else None
        return job if job and job.status in LIVE_STATUSES else None

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ApiError(f"no such run: {job_id}", status=404)
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)  # raises the 404 before anything is touched
        job.cancel()
        return job

    def start(self, project: str, target) -> Job:
        job = Job(uuid.uuid4().hex[:12], project)
        with self._lock:
            self._jobs[job.id] = job
            self._by_project[project] = job.id
            self._forget_old_jobs()
        thread = threading.Thread(target=target, args=(job,), daemon=True)
        thread.start()
        return job

    def _forget_old_jobs(self) -> None:
        """Drop the oldest finished jobs once more than the cap are held.

        The caller holds the lock, so this is the whole of the cleanup: no
        timer, no reaper thread, no dependency. A live job is never dropped —
        its id is the browser's only handle on a run, and losing it would also
        let a second run start against the same project and spend twice.
        """
        finished = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status not in LIVE_STATUSES
        ]
        if len(finished) <= MAX_RETAINED_JOBS:
            return
        for job_id in finished[: len(finished) - MAX_RETAINED_JOBS]:
            job = self._jobs.pop(job_id)
            # Otherwise the index outlives the job it names, and `active_for`
            # keeps answering for a project whose run is gone.
            if self._by_project.get(job.project) == job_id:
                del self._by_project[job.project]


# ---------------------------------------------------------------------------
# the API
# ---------------------------------------------------------------------------


class ArenaAPI:
    """Everything the browser can ask for."""

    def __init__(self, projects_dir: str | Path) -> None:
        self.projects_dir = Path(projects_dir).resolve()
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.jobs = JobManager()

    # ---- paths ---------------------------------------------------------

    def _project_dir(self, name: str) -> Path:
        if not SAFE_NAME.match(str(name or "")):
            raise ApiError(
                "A project name must be lowercase letters, numbers, dashes or "
                "underscores (up to 64 characters)."
            )
        path = (self.projects_dir / name).resolve()
        # Belt and braces: SAFE_NAME already excludes separators and "..", but
        # this is the check that must not be wrong, so it is made twice.
        if path.parent != self.projects_dir:
            raise ApiError("Invalid project name.", status=400)
        return path

    def _load(self, name: str) -> ProjectConfig:
        path = self._project_dir(name)
        if not path.is_dir():
            raise ApiError(f"No project called {name!r}.", status=404)
        try:
            return load_config(path)
        except ArenaError as exc:
            raise ApiError(lang.plain_error(str(exc))) from exc

    # ---- catalogs ------------------------------------------------------

    def catalog(self) -> dict[str, Any]:
        """Everything the wizard needs to render itself, in one request."""
        price_book = build_price_book(None)
        registry = ScorerRegistry()
        return {
            "presets": lang.JOB_PRESETS,
            "metric_language": lang.METRIC_LANGUAGE,
            "weightable_metrics": sorted(BUILTIN_METRICS),
            "demo_models": DEMO_MODELS,
            "real_models": self._real_models(price_book),
            "scorers": registry.describe(),
            "yaml": yaml_available(),
        }

    def _real_models(self, price_book: Any) -> list[dict[str, Any]]:
        """The priced catalog, annotated with whether this machine can call it."""
        models = []
        for model_id in price_book.known_models():
            card = price_book.get(model_id)
            provider = card.provider or ""
            spec = _Spec(model_id, provider)
            env = requires_api_key(spec)
            models.append(
                {
                    "model": model_id,
                    "display": card.display_name or model_id,
                    "provider": provider,
                    "input_usd_per_mtok": card.input_usd_per_mtok,
                    "output_usd_per_mtok": card.output_usd_per_mtok,
                    "context_tokens": card.context_tokens,
                    "api_key_env": env,
                    "available": _key_present(env),
                }
            )
        return models

    # ---- projects ------------------------------------------------------

    def list_projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        out = []
        for path in sorted(self.projects_dir.iterdir()):
            if not path.is_dir():
                continue
            try:
                config = load_config(path)
            except ArenaError:
                continue  # a folder that is not a project is not an error
            archived = bool(config.raw.get("archived"))
            if archived and not include_archived:
                # Archive has to actually hide things, or it is just a flag
                # nobody can see and the user reaches for delete instead.
                continue
            last = self._last_run(config)
            out.append(
                {
                    "name": path.name,
                    "project": config.project,
                    "description": (config.description or "").strip(),
                    "models": len(config.enabled_models),
                    "tests": self._count_tests(config),
                    "archived": archived,
                    "last_run": last,
                }
            )
        return out

    def _count_tests(self, config: ProjectConfig) -> int:
        try:
            return len(ArenaRunner.from_project(config.root).test_cases)
        except ArenaError:
            return 0

    def _last_run(self, config: ProjectConfig) -> dict[str, Any] | None:
        if not config.database.exists():
            return None
        try:
            with ResultStore(config.database) as store:
                runs = store.runs(config.project, limit=1)
        except Exception:  # noqa: BLE001 — a corrupt db must not blank the page
            return None
        if not runs:
            return None
        row = runs[0]
        return {
            "run_id": row.get("run_id"),
            "started_at": row.get("started_at"),
            "winner": row.get("winner"),
            "status": row.get("status"),
        }

    def describe_project(self, name: str) -> dict[str, Any]:
        """A project rendered for humans: what it tests, what it values, its cases."""
        config = self._load(name)
        runner = ArenaRunner.from_project(config.root)
        weights = config.metrics.normalized_weights()
        constraints = _constraints_dict(config.constraints)
        eval_types = {case.eval_type for case in runner.test_cases if case.eval_type}
        preset = None
        for eval_type in sorted(eval_types):
            preset = lang.preset_for_eval_type(eval_type)
            if preset:
                break

        return {
            "name": name,
            "project": config.project,
            "description": (config.description or "").strip(),
            "preset": preset,
            "eval_types": sorted(eval_types),
            "weights": weights,
            "weights_sentence": lang.explain_weights(weights),
            "constraints": constraints,
            "constraint_sentences": lang.explain_constraints(constraints),
            "targets": dict(config.metrics.targets),
            "run": {
                "trials": config.run.trials,
                "concurrency": config.run.concurrency,
                "timeout_s": config.run.timeout_s,
            },
            "models": [
                {
                    "key": spec.key,
                    "model": spec.model,
                    "label": spec.display,
                    "provider": resolve_provider(spec) or "",
                    "enabled": spec.enabled,
                    "api_key_env": requires_api_key(spec),
                    "ready": requires_api_key(spec) is None or _key_present(requires_api_key(spec)),
                    "simulated": str(spec.model).startswith("mock:"),
                }
                for spec in config.models
            ],
            "tests": [
                {
                    "id": case.id,
                    "input": case.input if isinstance(case.input, str) else json.dumps(case.input),
                    "reference": case.reference,
                    "eval_type": case.eval_type,
                    "tags": list(case.tags),
                    "weight": case.weight,
                }
                for case in runner.test_cases
            ],
            "preflight": self._preflight(runner),
            "editable": _is_editable(config),
        }

    def _preflight(self, runner: ArenaRunner) -> dict[str, Any]:
        """What would stop this run, said before the user clicks the button."""
        try:
            skipped = runner.preflight()
        except ArenaError as exc:
            return {"ok": False, "blocked": lang.plain_error(str(exc)), "skipped": {}}
        runnable = [s for s in runner.config.enabled_models if s.key not in skipped]
        planned = len(runnable) * len(runner.test_cases) * runner.config.run.trials
        return {
            "ok": bool(runnable) and bool(runner.test_cases),
            "blocked": None if runnable and runner.test_cases else _why_blocked(runner),
            "skipped": {
                key: lang.plain_error(reason) for key, reason in skipped.items()
            },
            "planned_calls": planned,
            "runnable_models": [s.key for s in runnable],
        }

    # ---- creating and editing -------------------------------------------

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _slug(payload.get("name") or "")
        path = self._project_dir(name)
        if path.exists():
            raise ApiError(f"A project called {name!r} already exists.", status=409)

        preset_id = payload.get("preset") or "sort"
        preset = lang.PRESETS_BY_ID.get(preset_id)
        if preset is None:
            raise ApiError(f"Unknown job type {preset_id!r}.")

        tests = _clean_tests(payload.get("tests") or [], preset["eval_type"])
        if not tests:
            raise ApiError("Add at least one example before creating the project.")

        path.mkdir(parents=True)
        config = _build_config(name, payload, preset)
        _write_structured(path / "config", config)
        _write_structured(
            path / "tests", {"defaults": {"eval_type": preset["eval_type"]}, "tests": tests}
        )
        return self.describe_project(name)

    def update_project(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Change what the project values without touching anything else."""
        config = self._load(name)
        raw = _read_config_file(config)

        if "weights" in payload:
            weights = _clean_weights(payload["weights"])
            raw.setdefault("metrics", {})["weights"] = weights
        if "targets" in payload:
            metrics = raw.setdefault("metrics", {})
            for metric, value in (payload["targets"] or {}).items():
                if metric not in BUILTIN_METRICS:
                    continue
                block = metrics.setdefault(metric, {})
                if value in (None, ""):
                    block.pop("target", None)
                    block.pop("budget_usd_per_1k_calls", None)
                    block.pop("target_ms", None)
                else:
                    block["target"] = float(value)
        if "constraints" in payload:
            raw["constraints"] = _clean_constraints(payload["constraints"])
        if "trials" in payload:
            raw.setdefault("run", {})["trials"] = max(1, min(50, int(payload["trials"])))
        if "models" in payload:
            raw["models"] = _clean_models(payload["models"])
        if "description" in payload:
            raw["description"] = str(payload["description"])

        _write_structured(_config_path(config).with_suffix(""), raw)
        return self.describe_project(name)

    def save_tests(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._load(name)
        files = config.discover_test_files()
        if len(files) != 1:
            raise ApiError(
                "This project keeps its test cases in several files, so the "
                "editor cannot safely rewrite them. Edit them on disk instead.",
                status=409,
            )
        existing = _read_structured(files[0])
        default_eval = (existing.get("defaults") or {}).get("eval_type") if isinstance(
            existing, dict
        ) else None
        tests = _clean_tests(payload.get("tests") or [], default_eval)
        if not tests:
            raise ApiError("A project needs at least one example.")
        body: dict[str, Any] = {}
        if default_eval:
            body["defaults"] = {"eval_type": default_eval}
        body["tests"] = tests
        _write_structured(files[0].with_suffix(""), body)
        return self.describe_project(name)

    # ---- running -------------------------------------------------------

    def start_run(self, name: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        config = self._load(name)

        existing = self.jobs.active_for(config.project)
        if existing is not None:
            # Double-clicking "Run" must not spend twice.
            return existing.snapshot()

        overrides: dict[str, Any] = {}
        if options.get("trials"):
            overrides["trials"] = max(1, min(50, int(options["trials"])))
        if options.get("models"):
            overrides["models"] = list(options["models"])

        def target(job: Job) -> None:
            try:
                runner = ArenaRunner.from_project(
                    config.root,
                    progress=job.on_event,
                    cancel_event=job.cancel_event,
                    **overrides,
                )
                result = runner.run()
                payload = self._present_run(result.leaderboard.to_dict(), config, result)
                with job._lock:  # noqa: SLF001 — same module, one writer
                    job.run_id = result.run_id
                    job.payload = payload
                    # A cancelled sweep produced real, partial results. Reporting
                    # it as "done" would present a truncated leaderboard as a
                    # complete one.
                    job.status = "cancelled" if job.cancel_event.is_set() else "done"
                    job.finished_at = time.time()
            except BaseException as exc:  # noqa: BLE001 — surfaced to the browser
                with job._lock:  # noqa: SLF001
                    job.status = "error"
                    job.error = lang.plain_error(str(exc))
                    job.error_detail = f"{type(exc).__name__}: {exc}"
                    job.finished_at = time.time()

        return self.jobs.start(config.project, target).snapshot()

    def cancel_run(self, job_id: str) -> dict[str, Any]:
        """Stop a sweep that is spending money. Idempotent."""
        job = self.jobs.get(job_id)
        job.cancel()
        return job.snapshot()

    # ---- lifecycle -----------------------------------------------------

    def delete_project(self, name: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        from ..service import projects as svc  # noqa: PLC0415

        query = query or {}
        return svc.delete_project(
            self.projects_dir,
            name,
            keep_results=_flag(query.get("keep_results")),
            dry_run=_flag(query.get("dry_run")),
        )

    def duplicate_project(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        from ..service import projects as svc  # noqa: PLC0415

        new_name = str(body.get("name") or body.get("new_name") or "").strip()
        if not new_name:
            raise ApiError("give the copy a name.")
        return svc.duplicate_project(self.projects_dir, name, new_name)

    def archive_project(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        from ..service import projects as svc  # noqa: PLC0415

        return svc.archive_project(self.projects_dir, name, bool(body.get("archived", True)))

    def list_runs(self, name: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        from ..service import runs as svc  # noqa: PLC0415

        query = query or {}
        return {
            "runs": svc.list_runs(
                self.projects_dir,
                name,
                limit=int(query.get("limit") or 50),
                include_deleted=_flag(query.get("include_deleted")),
            )
        }

    def delete_run(
        self, name: str, run_id: str, query: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        from ..service import runs as svc  # noqa: PLC0415

        query = query or {}
        return svc.delete_run(
            self.projects_dir,
            name,
            run_id,
            hard=_flag(query.get("hard")),
            dry_run=_flag(query.get("dry_run")),
        )

    def label_run(self, name: str, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from ..service import runs as svc  # noqa: PLC0415

        return svc.label_run(
            self.projects_dir, name, run_id,
            label=body.get("label"), notes=body.get("notes"),
        )

    def vacuum(self, name: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        from ..service import runs as svc  # noqa: PLC0415

        return svc.vacuum(self.projects_dir, name, dry_run=_flag((query or {}).get("dry_run")))

    def export_run(self, name: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        from ..service import export as svc  # noqa: PLC0415

        query = query or {}
        config = self._load(name)
        path = svc.export_run(
            self.projects_dir, name,
            query.get("run_id"), query.get("format", "html"),
            config.results_dir / "exports",
        )
        return {"path": str(path), "format": query.get("format", "html")}

    def settings(self) -> dict[str, Any]:
        from ..service import settings as svc  # noqa: PLC0415

        return svc.load()

    def update_settings(self, body: dict[str, Any]) -> dict[str, Any]:
        from ..service import settings as svc  # noqa: PLC0415

        return svc.save(body)

    def job_status(self, job_id: str) -> dict[str, Any]:
        return self.jobs.get(job_id).snapshot()

    def cancel_run(self, job_id: str) -> dict[str, Any]:
        """Stop a run that should not have been started.

        A misconfigured sweep against a paid API is the one thing the browser
        must be able to interrupt; the snapshot comes back so the page can say
        the stop was asked for before the run actually winds down.
        """
        return self.jobs.cancel(job_id).snapshot()

    # ---- results -------------------------------------------------------

    def history(self, name: str, limit: int = 20) -> dict[str, Any]:
        config = self._load(name)
        if not config.database.exists():
            return {"runs": [], "models": {}}
        with ResultStore(config.database) as store:
            runs = store.runs(config.project, limit=limit)
            series: dict[str, list[dict[str, Any]]] = {}
            for spec in config.enabled_models:
                history = store.model_history(config.project, spec.key, limit=limit)
                if history:
                    series[spec.key] = list(reversed(history))
        return {
            "runs": [
                {
                    "run_id": row.get("run_id"),
                    "started_at": row.get("started_at"),
                    "status": row.get("status"),
                    "winner": row.get("winner"),
                    "n_results": row.get("n_results"),
                    "total_cost_usd": row.get("total_cost_usd"),
                }
                for row in runs
            ],
            "models": series,
        }

    def stored_run(self, name: str, run_id: str | None = None) -> dict[str, Any]:
        """Re-present a finished run without re-running a single call."""
        config = self._load(name)
        board, resolved = self._leaderboard_from_store(config, run_id)
        payload = self._present_run(board.to_dict(), config)
        payload["run_id"] = resolved
        return payload

    def rescore(self, name: str, run_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        """"What if I cared more about cost?" — answered from stored results.

        The single most useful thing the UI can do that the CLI cannot: change
        the priorities and re-rank instantly, with no model calls and no spend.
        It runs the real :func:`build_leaderboard`, so a what-if and a fresh run
        with the same config can never disagree.
        """
        config = self._load(name)
        weights = _clean_weights(payload.get("weights") or config.metrics.weights)
        constraints = _clean_constraints(payload.get("constraints") or {})

        raw = _read_config_file(config)
        raw.setdefault("metrics", {})["weights"] = weights
        if "constraints" in payload:
            raw["constraints"] = constraints
        scratch = ProjectConfig.from_dict(raw, root=config.root, config_path=config.config_path)

        board, resolved = self._leaderboard_from_store(scratch, run_id)
        out = self._present_run(board.to_dict(), scratch)
        out["run_id"] = resolved
        out["hypothetical"] = True
        return out

    def _leaderboard_from_store(self, config: ProjectConfig, run_id: str | None):
        if not config.database.exists():
            raise ApiError("This project has not been run yet.", status=404)
        with ResultStore(config.database) as store:
            if run_id is None:
                runs = store.runs(config.project, limit=1)
                if not runs:
                    raise ApiError("This project has not been run yet.", status=404)
                run_id = runs[0]["run_id"]
            rows = store.results(run_id=run_id, limit=100_000)
        if not rows:
            raise ApiError(f"No stored results for run {run_id}.", status=404)

        by_model: dict[str, list[CallResult]] = {}
        for row in rows:
            by_model.setdefault(row["model_key"], []).append(_rehydrate(row))

        runner = ArenaRunner.from_project(config.root)
        weights_by_test = {case.id: case.weight for case in runner.test_cases}
        board = build_leaderboard(
            config,
            by_model,
            config.enabled_models,
            build_price_book(config),
            weights_by_test,
        )
        return board, run_id

    def _present_run(
        self, board: dict[str, Any], config: ProjectConfig, result: Any = None
    ) -> dict[str, Any]:
        """One shape for every results view: fresh run, stored run, or what-if."""
        constraints = _constraints_dict(config.constraints)
        return {
            "project": config.project,
            "run_id": getattr(result, "run_id", None),
            "verdict": lang.explain_verdict(board),
            "rows": [lang.summarise_entry(e) for e in board.get("entries", [])],
            "weights": board.get("weights", {}),
            "weights_sentence": lang.explain_weights(board.get("weights", {})),
            "constraints": constraints,
            "constraint_sentences": lang.explain_constraints(constraints),
            "notes": lang.plain_notes(board.get("notes", [])),
            "totals": {
                "cost_usd": getattr(result, "total_cost_usd", None),
                "duration_s": round(getattr(result, "duration_s", 0.0) or 0.0, 1),
                "errors": getattr(result, "error_count", None),
                "calls": len(getattr(result, "results", []) or []) or None,
            },
            "skipped_models": {
                key: lang.plain_error(reason)
                for key, reason in (getattr(result, "skipped_models", {}) or {}).items()
            },
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _Spec:
    """Minimal duck-type for the catalog's key lookup."""

    def __init__(self, model: str, provider: str) -> None:
        self.model = model
        self.provider = provider
        self.api_key_env = None
        self.api_base = None


def _flag(value: Any) -> bool:
    """A query-string flag. Absent, "0", "false" and "" are all false."""
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _key_present(env: str | None) -> bool:
    import os  # noqa: PLC0415

    return env is None or bool(os.environ.get(env))


def _why_blocked(runner: ArenaRunner) -> str:
    if not runner.test_cases:
        return "This project has no examples yet. Add at least one."
    return (
        "None of the selected models can run on this machine — they all need an "
        "API key that is not set. Add a simulated model to compare against."
    )


def _is_editable(config: ProjectConfig) -> bool:
    """Whether the visual editor can safely rewrite this project's files."""
    return len(config.discover_test_files()) == 1 and not config.hooks


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", str(value).strip().lower()).strip("_-")
    slug = re.sub(r"_{2,}", "_", slug)[:64]
    if not slug or not SAFE_NAME.match(slug):
        raise ApiError("Give the project a name using letters or numbers.")
    return slug


def _config_path(config: ProjectConfig) -> Path:
    return Path(config.config_path) if config.config_path else config.root / "config.yaml"


def _read_config_file(config: ProjectConfig) -> dict[str, Any]:
    raw = _read_structured(_config_path(config))
    if not isinstance(raw, dict):
        raise ApiError("This project's config file is not a mapping.", status=409)
    return raw


def _read_structured(path: Path) -> Any:
    from ..core.loaders import load_structured  # noqa: PLC0415

    return load_structured(path)


def _write_structured(stem: Path, data: Any) -> Path:
    """Write ``config``/``tests`` as YAML when we can, JSON when we cannot.

    Writing to the stem (no suffix) lets the caller stay out of the format
    question; an existing file of the other format is replaced so a project
    never ends up with both a config.yaml and a config.json.
    """
    if yaml_available():
        import yaml  # noqa: PLC0415

        path = stem.with_suffix(".yaml")
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=88)
        other = stem.with_suffix(".json")
    else:
        path = stem.with_suffix(".json")
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        other = stem.with_suffix(".yaml")

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    if other.exists():
        other.unlink()
    return path


def _constraints_dict(constraints: Any) -> dict[str, Any]:
    return {
        "min_accuracy": constraints.min_accuracy,
        "max_cost_per_1k_calls_usd": constraints.max_cost_per_1k_calls_usd,
        "max_latency_p95_ms": constraints.max_latency_p95_ms,
        "max_error_rate": constraints.max_error_rate,
        "min_context_tokens": constraints.min_context_tokens,
        "required_features": list(constraints.required_features),
        "privacy_required": list(constraints.privacy_required),
    }


def _clean_weights(raw: Any) -> dict[str, float]:
    weights: dict[str, float] = {}
    for name, value in (raw or {}).items():
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if weight > 0:
            weights[str(name)] = round(weight, 4)
    if not weights:
        raise ApiError("At least one thing has to matter — set a weight above zero.")
    return weights


def _clean_constraints(raw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    numeric = {
        "min_accuracy": (0.0, 1.0),
        "max_cost_per_1k_calls_usd": (0.0, 1e9),
        "max_latency_p95_ms": (0.0, 1e9),
        "max_error_rate": (0.0, 1.0),
    }
    for key, (low, high) in numeric.items():
        value = (raw or {}).get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ApiError(f"{key} must be a number.") from exc
        if not low <= number <= high:
            raise ApiError(f"{key} must be between {low} and {high}.")
        out[key] = number
    return out


def _clean_models(raw: Any) -> list[dict[str, Any]]:
    models = []
    for index, entry in enumerate(raw or []):
        if not isinstance(entry, dict):
            continue
        model = str(entry.get("model") or "").strip()
        if not model:
            raise ApiError(f"Model {index + 1} has no model id.")
        cleaned: dict[str, Any] = {
            "key": _slug(entry.get("key") or model),
            "model": model,
        }
        for optional in ("label", "provider", "api_base", "api_key_env"):
            if entry.get(optional):
                cleaned[optional] = str(entry[optional])
        if isinstance(entry.get("params"), dict):
            cleaned["params"] = entry["params"]
        if isinstance(entry.get("card"), dict):
            cleaned["card"] = entry["card"]
        if entry.get("enabled") is False:
            cleaned["enabled"] = False
        models.append(cleaned)
    if not models:
        raise ApiError("Pick at least one model to compare.")
    return models


def _clean_tests(raw: Any, default_eval: str | None) -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw or []):
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("input") or "").strip()
        if not text:
            continue
        test_id = _test_id(entry.get("id"), index, seen)
        case: dict[str, Any] = {"id": test_id, "input": text}
        reference = entry.get("reference")
        if reference not in (None, ""):
            case["reference"] = reference
        eval_type = entry.get("eval_type")
        if eval_type and eval_type != default_eval:
            case["eval_type"] = str(eval_type)
        tags = [str(t).strip() for t in (entry.get("tags") or []) if str(t).strip()]
        if tags:
            case["tags"] = tags
        try:
            weight = float(entry.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        if weight != 1.0:
            case["weight"] = weight
        tests.append(case)
        seen.add(test_id)
    return tests


def _test_id(raw: Any, index: int, seen: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", str(raw or f"case_{index + 1}").lower()).strip("_")
    base = base[:48] or f"case_{index + 1}"
    candidate, suffix = base, 2
    while candidate in seen:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _build_config(name: str, payload: dict[str, Any], preset: dict[str, Any]) -> dict[str, Any]:
    """Turn wizard answers into the same config.yaml a developer would write."""
    weights = _clean_weights(payload.get("weights") or preset["weights"])
    config: dict[str, Any] = {
        "project": name,
        "description": str(payload.get("description") or preset["blurb"]).strip(),
        "models": _clean_models(payload.get("models") or DEMO_MODELS[:3]),
        "defaults": {
            "system": str(payload.get("system") or preset["system"]).strip(),
            "max_tokens": int(payload.get("max_tokens") or preset["max_tokens"]),
            "temperature": 0,
        },
        "run": {
            "trials": max(1, min(50, int(payload.get("trials") or 3))),
            "concurrency": 8,
            "timeout_s": 60,
            "retries": 1,
        },
        "metrics": {"weights": weights},
        "scorers": {"default": preset["eval_type"]},
        "output": {"dir": "results", "formats": ["markdown", "json"]},
    }

    budget = payload.get("budget_usd_per_1k_calls")
    if budget not in (None, ""):
        config["metrics"]["cost"] = {"budget_usd_per_1k_calls": float(budget)}
    target_ms = payload.get("latency_target_ms")
    if target_ms not in (None, ""):
        config["metrics"]["latency"] = {"target_ms": float(target_ms)}

    constraints = _clean_constraints(payload.get("constraints") or {})
    if constraints:
        config["constraints"] = constraints

    if preset.get("needs_labels"):
        labels = [str(x).strip() for x in (payload.get("labels") or []) if str(x).strip()]
        if len(labels) < 2:
            raise ApiError("Sorting needs at least two categories.")
        config["scorers"]["options"] = {"classification": {"labels": labels}}
        config["defaults"]["system"] = (
            f"{config['defaults']['system']} The labels are: {', '.join(labels)}."
        )
    return config


#: Stored rows carry every field a CallResult has; rehydrating them lets a
#: what-if go through the identical scoring path as a live run.
def _rehydrate(row: dict[str, Any]) -> CallResult:
    return CallResult(
        model_key=row["model_key"],
        model=row["model"],
        test_id=row["test_id"],
        trial=row.get("trial") or 1,
        provider=row.get("provider") or "",
        eval_type=row.get("eval_type") or "",
        status=row.get("status") or "ok",
        score=row.get("score"),
        passed=bool(row["passed"]) if row.get("passed") is not None else None,
        output=row.get("output") or "",
        reference=row.get("reference"),
        reason=row.get("reason") or "",
        latency_ms=row.get("latency_ms"),
        input_tokens=row.get("input_tokens"),
        output_tokens=row.get("output_tokens"),
        cost_usd=row.get("cost_usd"),
        attempts=row.get("attempts") or 1,
        error=row.get("error"),
        tags=_split_tags(row.get("tags")),
        metrics=json.loads(row.get("metrics_json") or "{}"),
    )


def _split_tags(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw]
    return [part for part in str(raw).split(",") if part]
