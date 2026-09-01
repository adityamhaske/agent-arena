"""Project configuration — the only thing that differs between projects.

A project is a folder. The folder holds a ``config.yaml`` (or ``config.json``)
and one or more test files. Nothing in this module — or anywhere else in the
engine — knows what your project does.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ArenaError, ConfigError
from .loaders import STRUCTURED_SUFFIXES, load_structured

CONFIG_BASENAMES = ("config.yaml", "config.yml", "config.json", "arena.yaml", "arena.json")

#: Metrics the engine computes for every run. Projects may weight any of these
#: by name, plus any custom metric emitted by a scorer or post-process hook.
BUILTIN_METRICS = {
    # name          direction ("max" = higher is better)
    "accuracy": "max",
    "pass_rate": "max",
    "reliability": "max",
    "cost": "min",
    "latency": "min",
    "latency_p95": "min",
    "tokens": "min",
}

NORMALIZE_MODES = ("minmax", "target", "budget", "raw")


def _as_dict(value: Any, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _as_list(value: Any, where: str) -> list:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"{where} must be a list, got {type(value).__name__}")
    return list(value)


@dataclass
class ModelSpec:
    """One competitor in the arena."""

    key: str
    """Unique name for this entry in reports (defaults to the model id)."""

    model: str
    """The provider's model identifier, e.g. ``claude-opus-5``."""

    provider: str | None = None
    """Explicit provider. When omitted it is inferred from the model id."""

    run: str | None = None
    """A Python callable to evaluate instead of a model — ``file.py:function``.

    This is how a whole pipeline (retrieval, tools, several agents) competes on
    the same leaderboard as a single model call. See
    :mod:`agent_arena.connectors.callable_target`.
    """

    base_dir: Any = None
    """Project root, set during config load so ``run`` resolves relative to it."""

    params: dict[str, Any] = field(default_factory=dict)
    """Extra generation kwargs merged over the project defaults."""

    api_key_env: str | None = None
    api_base: str | None = None
    label: str | None = None
    card: dict[str, Any] = field(default_factory=dict)
    """Per-model overrides for the pricing/capability/privacy card."""

    enabled: bool = True

    @property
    def display(self) -> str:
        return self.label or self.key

    @classmethod
    def parse(cls, raw: Any, index: int) -> ModelSpec:
        where = f"models[{index}]"
        if isinstance(raw, str):
            return cls(key=raw, model=raw)
        raw = _as_dict(raw, where)

        run = raw.get("run") or raw.get("target") or raw.get("callable")
        model = raw.get("model") or raw.get("id") or raw.get("name")
        if not model and run:
            # A target is identified by what it runs, so it needs no model id.
            model = str(run)
        if not model:
            raise ConfigError(
                f"{where} needs a 'model' (or 'id') field, or a 'run' pointing at "
                "a callable like 'pipelines/rag.py:answer'"
            )

        key = raw.get("key") or raw.get("id") or model
        return cls(
            key=str(key),
            model=str(model),
            run=str(run) if run else None,
            provider=raw.get("provider"),
            params=_as_dict(raw.get("params"), f"{where}.params"),
            api_key_env=raw.get("api_key_env"),
            api_base=raw.get("api_base") or raw.get("base_url"),
            label=raw.get("label"),
            card=_as_dict(raw.get("card"), f"{where}.card"),
            enabled=bool(raw.get("enabled", True)),
        )


@dataclass
class RunSettings:
    trials: int = 1
    concurrency: int = 4
    timeout_s: float = 120.0
    retries: int = 2
    retry_backoff_s: float = 2.0
    fail_fast: bool = False
    seed: int | None = None

    @classmethod
    def parse(cls, raw: Any) -> RunSettings:
        raw = _as_dict(raw, "run")
        settings = cls(
            trials=int(raw.get("trials", 1)),
            concurrency=int(raw.get("concurrency", 4)),
            timeout_s=float(raw.get("timeout_s", 120.0)),
            retries=int(raw.get("retries", 2)),
            retry_backoff_s=float(raw.get("retry_backoff_s", 2.0)),
            fail_fast=bool(raw.get("fail_fast", False)),
            seed=raw.get("seed"),
        )
        if settings.trials < 1:
            raise ConfigError("run.trials must be >= 1")
        if settings.concurrency < 1:
            raise ConfigError("run.concurrency must be >= 1")
        if settings.retries < 0:
            raise ConfigError("run.retries must be >= 0")
        return settings


@dataclass
class MetricSettings:
    """How raw measurements become a single comparable number.

    ``weights`` may name any builtin metric or any custom metric a scorer or
    hook emits. Weights are normalised to sum to 1 so ``{accuracy: 5, cost: 3,
    latency: 2}`` and ``{accuracy: .5, cost: .3, latency: .2}`` are the same
    thing.
    """

    weights: dict[str, float] = field(default_factory=lambda: {"accuracy": 1.0})
    directions: dict[str, str] = field(default_factory=dict)
    normalize: dict[str, str] = field(default_factory=dict)
    targets: dict[str, float] = field(default_factory=dict)
    tie_breaker: str = "accuracy"

    @classmethod
    def parse(cls, raw: Any) -> MetricSettings:
        raw = _as_dict(raw, "metrics")
        weights_raw = _as_dict(raw.get("weights"), "metrics.weights")
        weights: dict[str, float] = {}
        for name, value in weights_raw.items():
            try:
                weight = float(value)
            except (TypeError, ValueError) as exc:
                raise ConfigError(
                    f"metrics.weights.{name} must be a number, got {value!r}"
                ) from exc
            if weight < 0:
                raise ConfigError(f"metrics.weights.{name} must be >= 0")
            weights[str(name)] = weight

        if not weights:
            weights = {"accuracy": 1.0}
        if sum(weights.values()) <= 0:
            raise ConfigError("metrics.weights must contain at least one positive weight")

        directions: dict[str, str] = {}
        normalize: dict[str, str] = {}
        targets: dict[str, float] = {}

        # Per-metric blocks: metrics.cost.{normalize,budget}, metrics.latency.{target_p95_ms}, …
        for name, value in raw.items():
            if name in ("weights", "tie_breaker"):
                continue
            block = _as_dict(value, f"metrics.{name}")
            direction = block.get("direction")
            if direction is not None:
                if direction not in ("max", "min"):
                    raise ConfigError(
                        f"metrics.{name}.direction must be 'max' or 'min', got {direction!r}"
                    )
                directions[name] = direction
            mode = block.get("normalize")
            if mode is not None:
                if mode not in NORMALIZE_MODES:
                    raise ConfigError(
                        f"metrics.{name}.normalize must be one of "
                        f"{', '.join(NORMALIZE_MODES)}, got {mode!r}"
                    )
                normalize[name] = mode
            # Explicit None checks, not `or`: a budget of 0 is a real (if
            # strict) ceiling and must not fall through to the next key.
            target = _first_not_none(
                block,
                ("target", "budget", "budget_usd_per_1k_calls",
                 "target_p95_ms", "target_ms"),
            )
            if target is not None:
                try:
                    targets[name] = float(target)
                except (TypeError, ValueError) as exc:
                    raise ConfigError(f"metrics.{name} target must be a number") from exc
                normalize.setdefault(name, "target")

        return cls(
            weights=weights,
            directions=directions,
            normalize=normalize,
            targets=targets,
            tie_breaker=str(raw.get("tie_breaker", "accuracy")),
        )

    def normalized_weights(self) -> dict[str, float]:
        total = sum(self.weights.values())
        return {name: weight / total for name, weight in self.weights.items()}

    def direction(self, metric: str) -> str:
        if metric in self.directions:
            return self.directions[metric]
        return BUILTIN_METRICS.get(metric, "max")

    def normalize_mode(self, metric: str) -> str:
        if metric in self.normalize:
            return self.normalize[metric]
        if metric in self.targets:
            return "target"
        # Accuracy-like metrics are already 0..1; everything else is relative.
        if metric in ("accuracy", "pass_rate", "reliability"):
            return "raw"
        return "minmax"


@dataclass
class Constraints:
    """Hard gates. A model failing any of these is disqualified, not penalised.

    Capability and privacy facts come from the model card (built-in catalog,
    overridden per project). ``min_accuracy`` is measured from the run itself.
    """

    privacy_required: list[str] = field(default_factory=list)
    required_features: list[str] = field(default_factory=list)
    min_context_tokens: int | None = None
    max_cost_per_1k_calls_usd: float | None = None
    max_latency_p95_ms: float | None = None
    min_accuracy: float | None = None
    max_error_rate: float | None = None
    allow_unknown_card: bool = True
    """When False, a model with no card entry fails instead of passing unchecked."""

    @classmethod
    def parse(cls, raw: Any) -> Constraints:
        raw = _as_dict(raw, "constraints")
        privacy = _as_dict(raw.get("privacy"), "constraints.privacy")
        deployment = _as_dict(raw.get("deployment"), "constraints.deployment")

        max_context = deployment.get("min_context_tokens") or deployment.get("min_context")
        return cls(
            privacy_required=[str(x) for x in _as_list(
                privacy.get("required", privacy.get("requirements")),
                "constraints.privacy.required",
            )],
            required_features=[str(x) for x in _as_list(
                deployment.get("required_features", deployment.get("features")),
                "constraints.deployment.required_features",
            )],
            min_context_tokens=int(max_context) if max_context else None,
            max_cost_per_1k_calls_usd=_opt_float(
                raw.get("max_cost_per_1k_calls_usd"), "constraints.max_cost_per_1k_calls_usd"
            ),
            max_latency_p95_ms=_opt_float(
                raw.get("max_latency_p95_ms"), "constraints.max_latency_p95_ms"
            ),
            min_accuracy=_opt_float(raw.get("min_accuracy"), "constraints.min_accuracy"),
            max_error_rate=_opt_float(raw.get("max_error_rate"), "constraints.max_error_rate"),
            allow_unknown_card=bool(
                raw.get("allow_unknown_card", deployment.get("allow_unknown_card", True))
            ),
        )

    @property
    def any_static(self) -> bool:
        """True when there is something to check before running a single test."""
        return bool(
            self.privacy_required
            or self.required_features
            or self.min_context_tokens
            or not self.allow_unknown_card
        )


def _first_not_none(block: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if block.get(key) is not None:
            return block[key]
    return None


def _opt_float(value: Any, where: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where} must be a number, got {value!r}") from exc


@dataclass
class ProjectConfig:
    """The parsed, validated contents of a project folder's config file."""

    project: str
    root: Path
    config_path: Path | None = None
    description: str = ""
    models: list[ModelSpec] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    run: RunSettings = field(default_factory=RunSettings)
    metrics: MetricSettings = field(default_factory=MetricSettings)
    constraints: Constraints = field(default_factory=Constraints)
    test_paths: list[str] = field(default_factory=list)
    test_filter: dict[str, Any] = field(default_factory=dict)
    scorer_paths: list[str] = field(default_factory=list)
    default_eval_type: str = "exact_match"
    scorer_options: dict[str, dict[str, Any]] = field(default_factory=dict)
    judge: dict[str, Any] = field(default_factory=dict)
    hooks: dict[str, str] = field(default_factory=dict)
    pricing_path: str | None = None
    pricing_overrides: dict[str, Any] = field(default_factory=dict)
    output_dir: str = "results"
    db_path: str | None = None
    formats: list[str] = field(default_factory=lambda: ["markdown", "json"])
    raw: dict[str, Any] = field(default_factory=dict)

    # ---- path helpers -------------------------------------------------

    def resolve(self, path: str | Path) -> Path:
        """Resolve a config-relative path against the project folder."""
        candidate = Path(path)
        return candidate if candidate.is_absolute() else (self.root / candidate)

    @property
    def results_dir(self) -> Path:
        return self.resolve(self.output_dir)

    @property
    def database(self) -> Path:
        return self.resolve(self.db_path or Path(self.output_dir) / "arena.sqlite")

    @property
    def enabled_models(self) -> list[ModelSpec]:
        return [m for m in self.models if m.enabled]

    # ---- construction -------------------------------------------------

    @classmethod
    def from_dict(
        cls, data: Any, root: str | Path, config_path: str | Path | None = None
    ) -> ProjectConfig:
        data = _as_dict(data, "config")
        root = Path(root)

        # `targets:` is the same list under a name that reads better when the
        # things being compared are pipelines rather than models.
        raw_models = _as_list(data.get("models"), "models") + _as_list(
            data.get("targets"), "targets"
        )
        if not raw_models:
            raise ConfigError(
                "config must list at least one entry under 'models' (or 'targets'). "
                "Example:\n  models:\n    - claude-opus-5\n    - mock:baseline\n"
                "  targets:\n    - key: my_pipeline\n      run: pipelines/rag.py:answer"
            )
        models = [ModelSpec.parse(raw, i) for i, raw in enumerate(raw_models)]
        for model in models:
            model.base_dir = root

        seen: dict[str, int] = {}
        for model in models:
            if model.key in seen:
                raise ConfigError(
                    f"duplicate model key {model.key!r}; give one of them an explicit "
                    "'key' so results stay distinguishable"
                )
            seen[model.key] = 1

        tests_block = data.get("tests")
        if isinstance(tests_block, list):
            test_paths, test_filter = [str(p) for p in tests_block], {}
        else:
            tests_block = _as_dict(tests_block, "tests")
            test_paths = [str(p) for p in _as_list(tests_block.get("paths"), "tests.paths")]
            test_filter = {
                k: v for k, v in tests_block.items() if k not in ("paths",)
            }

        scorers_block = _as_dict(data.get("scorers"), "scorers")
        output_block = _as_dict(data.get("output"), "output")
        pricing_block = data.get("pricing")
        if isinstance(pricing_block, str):
            pricing_block = {"path": pricing_block}
        pricing_block = _as_dict(pricing_block, "pricing")

        hooks_raw = _as_dict(data.get("hooks"), "hooks")
        hooks = {str(k): str(v) for k, v in hooks_raw.items() if v}

        config = cls(
            project=str(data.get("project") or data.get("name") or root.name),
            root=root,
            config_path=Path(config_path) if config_path else None,
            description=str(data.get("description", "")),
            models=models,
            defaults=_as_dict(data.get("defaults"), "defaults"),
            run=RunSettings.parse(data.get("run")),
            metrics=MetricSettings.parse(data.get("metrics")),
            constraints=Constraints.parse(data.get("constraints")),
            test_paths=test_paths,
            test_filter=test_filter,
            scorer_paths=[
                str(p) for p in _as_list(scorers_block.get("paths"), "scorers.paths")
            ],
            default_eval_type=str(scorers_block.get("default", "exact_match")),
            scorer_options={
                str(k): _as_dict(v, f"scorers.options.{k}")
                for k, v in _as_dict(scorers_block.get("options"), "scorers.options").items()
            },
            judge=_as_dict(data.get("judge"), "judge"),
            hooks=hooks,
            pricing_path=pricing_block.get("path"),
            pricing_overrides=_as_dict(pricing_block.get("models"), "pricing.models"),
            output_dir=str(output_block.get("dir", "results")),
            db_path=output_block.get("db"),
            formats=[str(f) for f in _as_list(
                output_block.get("formats", ["markdown", "json"]), "output.formats"
            )],
            raw=data,
        )
        config.validate()
        return config

    @classmethod
    def load(cls, project_path: str | Path) -> ProjectConfig:
        """Load ``<project_path>/config.yaml`` (or a config file given directly)."""
        path = Path(project_path)

        if path.is_file():
            config_path, root = path, path.parent
        elif path.is_dir():
            config_path = None
            for basename in CONFIG_BASENAMES:
                candidate = path / basename
                if candidate.is_file():
                    config_path = candidate
                    break
            if config_path is None:
                raise ConfigError(
                    f"No config file in {path}. Expected one of: "
                    f"{', '.join(CONFIG_BASENAMES)}.\n"
                    "Run `arena init <path>` to scaffold a project."
                )
            root = path
        else:
            raise ConfigError(f"Project path does not exist: {path}")

        try:
            data = load_structured(config_path)
        except ArenaError as exc:
            raise ConfigError(str(exc)) from exc
        return cls.from_dict(data, root=root, config_path=config_path)

    # ---- validation ---------------------------------------------------

    def validate(self) -> None:
        known = set(BUILTIN_METRICS)
        for name in self.metrics.weights:
            if name not in known and not self.metrics.direction(name):
                raise ConfigError(f"metrics.weights.{name}: unknown metric direction")

        for mode in self.metrics.normalize.values():
            if mode not in NORMALIZE_MODES:
                raise ConfigError(f"metrics normalize mode {mode!r} is not supported")

        for metric, mode in self.metrics.normalize.items():
            if mode in ("target", "budget") and metric not in self.metrics.targets:
                raise ConfigError(
                    f"metrics.{metric}.normalize is {mode!r} but no target/budget was given"
                )

        for path in self.test_paths:
            resolved = self.resolve(path)
            if not resolved.exists():
                raise ConfigError(f"tests.paths entry does not exist: {resolved}")

        for path in self.scorer_paths:
            resolved = self.resolve(path)
            if not resolved.exists():
                raise ConfigError(f"scorers.paths entry does not exist: {resolved}")

        for spec in self.models:
            if not spec.run:
                continue
            if ":" not in spec.run:
                raise ConfigError(
                    f"model {spec.key!r}: run must be 'path/to/file.py:function' "
                    f"or 'package.module:function', got {spec.run!r}"
                )
            target, _, _ = spec.run.partition(":")
            if target.endswith(".py") and not self.resolve(target).exists():
                raise ConfigError(
                    f"model {spec.key!r}: run target does not exist: {self.resolve(target)}"
                )

        if self.pricing_path and not self.resolve(self.pricing_path).exists():
            raise ConfigError(f"pricing.path does not exist: {self.resolve(self.pricing_path)}")

    # ---- overrides ----------------------------------------------------

    def apply_overrides(self, **overrides: Any) -> ProjectConfig:
        """Apply CLI/API overrides in place and return self, for chaining."""
        model_filter = overrides.pop("models", None)
        if model_filter:
            wanted = {str(m) for m in model_filter}
            matched = [m for m in self.models if m.key in wanted or m.model in wanted]
            missing = wanted - {m.key for m in matched} - {m.model for m in matched}
            if missing:
                available = ", ".join(m.key for m in self.models)
                raise ConfigError(
                    f"unknown model(s): {', '.join(sorted(missing))}. Available: {available}"
                )
            self.models = matched

        for key in ("trials", "concurrency", "timeout_s", "retries", "fail_fast"):
            value = overrides.pop(key, None)
            if value is not None:
                setattr(self.run, key, value)

        for key in ("limit", "tags", "ids", "exclude_tags"):
            value = overrides.pop(key, None)
            if value is not None:
                self.test_filter[key] = value

        for key, attr in (("output_dir", "output_dir"), ("db", "db_path")):
            value = overrides.pop(key, None)
            if value is not None:
                setattr(self, attr, value)

        tests = overrides.pop("tests", None)
        if tests:
            self.test_paths = [str(t) for t in _as_list(tests, "tests")]

        if overrides:
            raise ConfigError(f"unknown override(s): {', '.join(sorted(overrides))}")
        return self

    # ---- discovery ----------------------------------------------------

    def discover_test_files(self) -> list[Path]:
        """Find the project's test files.

        Explicit ``tests.paths`` wins; otherwise every ``test*``-named
        structured file in the project root plus everything under ``tests/``
        is picked up, so a project can just drop in ``tests.jsonl``.
        """
        if self.test_paths:
            files: list[Path] = []
            for entry in self.test_paths:
                resolved = self.resolve(entry)
                if resolved.is_dir():
                    files.extend(_structured_files(resolved))
                else:
                    files.append(resolved)
            return _dedupe(files)

        found = [
            p
            for p in sorted(self.root.iterdir())
            if p.is_file()
            and p.suffix.lower() in STRUCTURED_SUFFIXES
            and p.stem.lower().startswith("test")
        ]
        tests_dir = self.root / "tests"
        if tests_dir.is_dir():
            found.extend(_structured_files(tests_dir))

        if not found:
            raise ConfigError(
                f"No test files found in {self.root}. Add a 'tests.jsonl' / 'tests.yaml', "
                "a 'tests/' folder, or point 'tests.paths' at your files."
            )
        return _dedupe(found)

    def env_for(self, model: ModelSpec) -> str | None:
        """Read the API key for a model, if its env var is set."""
        if model.api_key_env:
            return os.environ.get(model.api_key_env)
        return None


def _structured_files(directory: Path) -> list[Path]:
    return sorted(
        p
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in STRUCTURED_SUFFIXES
    )


def _dedupe(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def load_config(project_path: str | Path, **overrides: Any) -> ProjectConfig:
    """Load a project config and apply overrides."""
    config = ProjectConfig.load(project_path)
    if overrides:
        config.apply_overrides(**overrides)
    return config
