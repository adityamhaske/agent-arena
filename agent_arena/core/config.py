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

#: What to do when a run walks through its budget ceiling.
BUDGET_ACTIONS = ("stop", "warn")

#: A profile may also name a generic OpenAI-compatible endpoint. That is not
#: a connector of its own — it is the ``local`` HTTP connector pointed at a
#: ``base_url`` — but it is what people call these gateways, so it is spelled
#: the way they will write it.
OPENAI_COMPATIBLE = "openai_compatible"


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


def _provider_kinds() -> set[str]:
    """The connector kinds a provider profile is allowed to name.

    Read at call time rather than imported at module scope: a host application
    can add a connector with ``register_connector`` after import, and a config
    naming that connector must still parse.
    """
    from ..connectors.registry import CONNECTORS

    return set(CONNECTORS) | {OPENAI_COMPATIBLE}


@dataclass
class ProviderSpec:
    """A named endpoint profile: *where* a model call goes, and *how*.

    In v1 the endpoint was described inline on every model entry (``api_base``,
    ``api_key_env``), which makes the three things people actually need
    impossible: two API keys for the same vendor in one run, a corporate
    gateway wanting custom headers and a private CA, and a rate limit that
    belongs to an endpoint rather than to a model. A profile is declared once
    under ``providers:`` and referenced by ``id`` from any number of models.

    Declaring nothing keeps v1 behaviour exactly. A model with no ``provider:``
    — or with a bare vendor kind like ``provider: anthropic`` — is routed by
    the connector registry the way it always was.
    """

    id: str
    """The name a model references in its ``provider:`` field."""

    kind: str
    """Which connector speaks this endpoint's protocol: ``openai``,
    ``anthropic``, ``local``, ``openai_compatible``, …"""

    base_url: str | None = None
    """Endpoint root. ``None`` means the vendor's own default."""

    api_key_ref: str | None = None
    """A *reference* to a credential (``env:OPENAI_API_KEY``), never a value.
    Resolving it belongs to :mod:`agent_arena.service.secrets`, not here."""

    headers: dict[str, str] = field(default_factory=dict)
    """Extra HTTP headers — the corporate-gateway case (a tenant id, a
    routing tag) that no vendor SDK has a field for."""

    timeout_s: float | None = None
    """Per-request ceiling for this endpoint, overriding ``run.timeout_s``."""

    verify_tls: bool | str = True
    """``True``, ``False``, or a path to a CA bundle for a private authority.

    ``False`` turns certificate checking off entirely. Nothing in this module
    warns about that, deliberately — this dataclass only parses. Whoever opens
    the connection owns telling the user their traffic is unverified.
    """

    proxy: str | None = None
    """Proxy URL for this endpoint alone, so one gateway can go through a
    corporate proxy while the rest of the run does not."""

    model_prefix: str | None = None
    """Prepended to the model id on the way out, for gateways that namespace
    their catalog (``team-a/gpt-4o``)."""

    rate_limit: dict[str, Any] = field(default_factory=dict)
    """``rpm`` / ``tpm`` / ``concurrency``. Unknown keys pass through so a
    connector can read its own knob without a change here."""

    retry: dict[str, Any] = field(default_factory=dict)
    """``attempts`` / ``backoff_s`` / ``jitter`` / ``respect_retry_after``."""

    params: dict[str, Any] = field(default_factory=dict)
    """Extra client kwargs, merged the way ``ModelSpec.params`` is."""

    @classmethod
    def parse(cls, raw: Any, index: int) -> ProviderSpec:
        where = f"providers[{index}]"
        raw = _as_dict(raw, where)

        identifier = raw.get("id") or raw.get("name")
        if not identifier:
            raise ConfigError(
                f"{where} needs an 'id' — that is the name models reference. "
                "Example:\n  providers:\n    - id: openai_prod\n      kind: openai"
            )
        identifier = str(identifier)

        kinds = _provider_kinds()
        kind = raw.get("kind") or raw.get("type")
        if not kind:
            raise ConfigError(
                f"{where} ({identifier!r}) needs a 'kind' saying which connector "
                f"speaks to it. Valid kinds: {', '.join(sorted(kinds))}"
            )
        kind = str(kind)
        if kind not in kinds:
            raise ConfigError(
                f"{where} ({identifier!r}): unknown kind {kind!r}. "
                f"Valid kinds: {', '.join(sorted(kinds))}"
            )

        # `api_key:` is what somebody writes in YAML; `api_key_ref:` is what it
        # means. Both hold a reference, never a literal credential.
        api_key_ref = _first_not_none(raw, ("api_key_ref", "api_key"))

        verify = _first_not_none(raw, ("verify_tls", "verify"))
        if verify is None:
            verify = True
        if not isinstance(verify, (bool, str)):
            raise ConfigError(
                f"{where}.verify_tls must be true, false, or a path to a CA "
                f"bundle, got {verify!r}"
            )

        timeout_s = _opt_float(raw.get("timeout_s"), f"{where}.timeout_s")
        if timeout_s is not None and timeout_s <= 0:
            raise ConfigError(
                f"{where}.timeout_s must be > 0; omit it to inherit run.timeout_s"
            )

        rate_limit = _as_dict(raw.get("rate_limit"), f"{where}.rate_limit")
        for name in ("rpm", "tpm", "concurrency", "burst"):
            value = _opt_float(rate_limit.get(name), f"{where}.rate_limit.{name}")
            if value is not None and value <= 0:
                raise ConfigError(
                    f"{where}.rate_limit.{name} must be > 0; "
                    "omit it to mean 'no limit'"
                )

        retry = _as_dict(raw.get("retry"), f"{where}.retry")
        for name in ("attempts", "backoff_s"):
            value = _opt_float(retry.get(name), f"{where}.retry.{name}")
            if value is not None and value < 0:
                raise ConfigError(f"{where}.retry.{name} must be >= 0, got {value!r}")

        return cls(
            id=identifier,
            kind=kind,
            base_url=_opt_str(_first_not_none(raw, ("base_url", "api_base"))),
            api_key_ref=_opt_str(api_key_ref),
            headers={
                str(k): str(v)
                for k, v in _as_dict(raw.get("headers"), f"{where}.headers").items()
            },
            timeout_s=timeout_s,
            verify_tls=verify,
            proxy=_opt_str(raw.get("proxy")),
            model_prefix=_opt_str(raw.get("model_prefix")),
            rate_limit=rate_limit,
            retry=retry,
            params=_as_dict(raw.get("params"), f"{where}.params"),
        )

    def to_dict(self) -> dict[str, Any]:
        """A JSON-safe view of the profile, for API responses and diffs.

        This never carries a secret VALUE. ``api_key_ref`` is the reference the
        user wrote and resolution happens elsewhere, at the point of use — a
        resolved key placed here would travel straight into a browser.
        """
        return {
            "id": self.id,
            "kind": self.kind,
            "base_url": self.base_url,
            "api_key_ref": self.api_key_ref,
            "headers": dict(self.headers),
            "timeout_s": self.timeout_s,
            "verify_tls": self.verify_tls,
            "proxy": self.proxy,
            "model_prefix": self.model_prefix,
            "rate_limit": dict(self.rate_limit),
            "retry": dict(self.retry),
            "params": dict(self.params),
        }


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


@dataclass
class StatisticsSettings:
    """How much evidence to demand before calling a winner.

    On by default. The whole point of the arena is refusing to claim more than
    the data supports, and an interval is the honest form of that — leaving it
    off by default would make the dishonest presentation the easy one.
    """

    enabled: bool = True
    resamples: int = 2000
    confidence: float = 0.95
    seed: int = 0

    @classmethod
    def parse(cls, raw: Any) -> StatisticsSettings:
        if raw is None:
            return cls()
        if isinstance(raw, bool):
            return cls(enabled=raw)
        raw = _as_dict(raw, "statistics")
        confidence = float(raw.get("confidence", 0.95))
        if not 0.5 < confidence < 1.0:
            raise ConfigError(
                f"statistics.confidence must be between 0.5 and 1.0, got {confidence!r}"
            )
        resamples = int(raw.get("resamples", 2000))
        if resamples < 100:
            raise ConfigError(
                f"statistics.resamples must be at least 100, got {resamples}; "
                "fewer than that gives an unstable interval"
            )
        return cls(
            enabled=bool(raw.get("enabled", True)),
            resamples=resamples,
            confidence=confidence,
            seed=int(raw.get("seed", 0)),
        )


@dataclass
class WatchSettings:
    """Defaults for `arena watch`, so a scheduled invocation needs no flags.

    Both fields are optional and CLI flags always win, matching the pattern
    everywhere else in this file: config sets the default, the flag overrides
    it for one run.
    """

    drift_threshold: float = 0.05
    webhook: str | None = None

    @classmethod
    def parse(cls, raw: Any) -> WatchSettings:
        if raw is None:
            return cls()
        raw = _as_dict(raw, "watch")
        threshold = float(raw.get("drift_threshold", 0.05))
        if not 0.0 < threshold < 1.0:
            raise ConfigError(
                f"watch.drift_threshold must be between 0 and 1, got {threshold!r}"
            )
        webhook = raw.get("webhook")
        return cls(drift_threshold=threshold, webhook=str(webhook) if webhook else None)


@dataclass
class BudgetSettings:
    """What a run may spend before the harness stops or merely complains.

    Every amount is optional and ``None`` means "no ceiling" — which is what a
    config with no ``budgets:`` block gets, so nothing changes for one. This is
    parsed intent only; enforcement belongs to whoever is spending the money.
    """

    max_run_usd: float | None = None
    """Ceiling for the whole run, across every model in it."""

    max_model_usd: float | None = None
    """Ceiling for any single model, so one runaway entry cannot eat the run."""

    confirm_above_usd: float | None = None
    """Estimated cost above which an interface should ask before starting."""

    on_exceed: str = "stop"
    """``stop`` (default) or ``warn``. Stopping is the default because the
    surprising part of an evaluation should never be the bill."""

    @classmethod
    def parse(cls, raw: Any) -> BudgetSettings:
        raw = _as_dict(raw, "budgets")
        settings = cls(
            max_run_usd=_opt_float(raw.get("max_run_usd"), "budgets.max_run_usd"),
            max_model_usd=_opt_float(raw.get("max_model_usd"), "budgets.max_model_usd"),
            confirm_above_usd=_opt_float(
                raw.get("confirm_above_usd"), "budgets.confirm_above_usd"
            ),
            on_exceed=str(raw.get("on_exceed", "stop")),
        )
        for name in ("max_run_usd", "max_model_usd", "confirm_above_usd"):
            amount = getattr(settings, name)
            if amount is not None and amount < 0:
                raise ConfigError(
                    f"budgets.{name} must be >= 0, got {amount!r}; "
                    "remove the key to mean 'no ceiling'"
                )
        if settings.on_exceed not in BUDGET_ACTIONS:
            raise ConfigError(
                f"budgets.on_exceed must be one of {', '.join(BUDGET_ACTIONS)}, "
                f"got {settings.on_exceed!r}"
            )
        return settings


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


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


@dataclass
class ProjectConfig:
    """The parsed, validated contents of a project folder's config file."""

    project: str
    root: Path
    config_path: Path | None = None
    description: str = ""
    models: list[ModelSpec] = field(default_factory=list)
    providers: list[ProviderSpec] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    run: RunSettings = field(default_factory=RunSettings)
    metrics: MetricSettings = field(default_factory=MetricSettings)
    constraints: Constraints = field(default_factory=Constraints)
    budgets: BudgetSettings = field(default_factory=BudgetSettings)
    statistics: StatisticsSettings = field(default_factory=StatisticsSettings)
    watch: WatchSettings = field(default_factory=WatchSettings)
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

    def provider_for(self, spec: ModelSpec) -> ProviderSpec | None:
        """The declared endpoint profile a model uses, if it names one.

        ``None`` is not a failure — it is the v1 answer, and it is what keeps
        every config written before ``providers:`` existed working unchanged.
        A model with no ``provider:``, or with a bare vendor kind such as
        ``provider: anthropic``, resolves to ``None`` so the connector registry
        routes it exactly as it does today.
        """
        if not spec.provider:
            return None
        wanted = str(spec.provider)
        for profile in self.providers:
            if profile.id == wanted:
                return profile
        return None

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

        # Additive by design: a config with neither block gets an empty profile
        # list and budgets that gate nothing, which is v1 behaviour exactly.
        providers = [
            ProviderSpec.parse(entry, i)
            for i, entry in enumerate(_as_list(data.get("providers"), "providers"))
        ]
        budgets = BudgetSettings.parse(data.get("budgets"))

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
            providers=providers,
            defaults=_as_dict(data.get("defaults"), "defaults"),
            run=RunSettings.parse(data.get("run")),
            metrics=MetricSettings.parse(data.get("metrics")),
            constraints=Constraints.parse(data.get("constraints")),
            budgets=budgets,
            statistics=StatisticsSettings.parse(data.get("statistics")),
            watch=WatchSettings.parse(data.get("watch")),
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
        declared: dict[str, ProviderSpec] = {}
        for profile in self.providers:
            if profile.id in declared:
                raise ConfigError(
                    f"duplicate provider id {profile.id!r}; a model selects a profile "
                    "by id, so give one of them a different 'id'"
                )
            declared[profile.id] = profile

        kinds = _provider_kinds()
        for spec in self.models:
            if not spec.provider:
                continue
            name = str(spec.provider)
            # A bare vendor kind is v1 syntax: `provider: anthropic` means "use
            # the registry's anthropic connector" and must keep meaning that.
            if name in declared or name in kinds:
                continue
            raise ConfigError(
                f"model {spec.key!r}: provider {name!r} is neither a declared "
                f"providers[].id ({', '.join(sorted(declared)) or 'none declared'}) "
                f"nor a vendor kind ({', '.join(sorted(kinds))}). Declare it under "
                "'providers:' or name one of those kinds."
            )

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
