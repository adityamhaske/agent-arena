"""Model cards: price, context window, features, privacy posture.

Three layers, later ones winning: the shipped catalog, the project's own
pricing file (``pricing.path``), and per-model ``card:`` overrides in the model
list. A model with no card is *not* assigned a guessed price — its cost metric
is reported as unknown, which the report and the composite both handle
explicitly rather than silently treating as free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.errors import ArenaError, ConfigError
from ..core.loaders import load_structured

CATALOG_PATH = Path(__file__).with_name("model_cards.json")

#: Feature names people write in configs, mapped to the catalog's vocabulary.
FEATURE_ALIASES = {
    "tools": "function_calling",
    "tool_use": "function_calling",
    "tool_calling": "function_calling",
    "json_mode": "structured_outputs",
    "json_schema": "structured_outputs",
    "images": "vision",
    "image_input": "vision",
    "caching": "prompt_caching",
    "thinking": "adaptive_thinking",
    "extended_thinking": "adaptive_thinking",
    "batching": "batch",
}

PRIVACY_ALIASES = {
    "data_processing_agreement": "dpa",
    "no_training": "training_opt_out",
    "opt_out": "training_opt_out",
    "zdr": "zero_data_retention",
    "self_hosted": "on_prem",
    "on_premise": "on_prem",
}

_PROVIDER_PREFIXES = (
    "anthropic.",
    "anthropic/",
    "openai/",
    "azure/",
    "vertex_ai/",
    "gemini/",
    "bedrock/",
    "us.",
    "eu.",
)


@dataclass
class ModelCard:
    """What we know about a model, beyond how it answers."""

    model: str
    known: bool = False
    provider: str | None = None
    display_name: str | None = None
    input_usd_per_mtok: float | None = None
    output_usd_per_mtok: float | None = None
    cache_read_usd_per_mtok: float | None = None
    cache_write_usd_per_mtok: float | None = None
    context_tokens: int | None = None
    max_output_tokens: int | None = None
    features: set[str] = field(default_factory=set)
    privacy: dict[str, bool] = field(default_factory=dict)
    notes: str = ""
    as_of: str = ""

    @property
    def has_pricing(self) -> bool:
        return self.input_usd_per_mtok is not None and self.output_usd_per_mtok is not None

    def cost_usd(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float | None:
        """Cost of one call, or ``None`` when the card carries no pricing."""
        if not self.has_pricing:
            return None
        million = 1_000_000
        total = (input_tokens / million) * float(self.input_usd_per_mtok)
        total += (output_tokens / million) * float(self.output_usd_per_mtok)
        if cache_read_tokens and self.cache_read_usd_per_mtok is not None:
            total += (cache_read_tokens / million) * float(self.cache_read_usd_per_mtok)
        if cache_write_tokens and self.cache_write_usd_per_mtok is not None:
            total += (cache_write_tokens / million) * float(self.cache_write_usd_per_mtok)
        return total

    def missing_features(self, required: list[str]) -> list[str]:
        wanted = {FEATURE_ALIASES.get(f, f) for f in required}
        return sorted(wanted - self.features)

    def missing_privacy(self, required: list[str]) -> list[str]:
        missing = []
        for raw in required:
            key = PRIVACY_ALIASES.get(raw, raw)
            if self.privacy.get(key) is not True:
                missing.append(key)
        return missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "known": self.known,
            "provider": self.provider,
            "display_name": self.display_name,
            "input_usd_per_mtok": self.input_usd_per_mtok,
            "output_usd_per_mtok": self.output_usd_per_mtok,
            "context_tokens": self.context_tokens,
            "max_output_tokens": self.max_output_tokens,
            "features": sorted(self.features),
            "privacy": dict(self.privacy),
            "notes": self.notes,
            "as_of": self.as_of,
        }


class PriceBook:
    """Resolves a model id to a :class:`ModelCard`."""

    def __init__(self, catalog: dict[str, Any] | None = None) -> None:
        data = catalog if catalog is not None else _load_catalog()
        self.as_of = str(data.get("as_of", ""))
        self._entries: dict[str, dict[str, Any]] = dict(data.get("models") or {})
        self._aliases: dict[str, str] = dict(data.get("aliases") or {})
        self._overrides: dict[str, dict[str, Any]] = {}
        self._cache: dict[str, ModelCard] = {}

    # ---- layering -----------------------------------------------------

    #: Past this many days, a catalog is treated as stale enough to warn about.
    #: Prices move; the roadmap's own wording is "warn past 90 days" and this
    #: is that number given a name other code can reference.
    STALE_AFTER_DAYS = 90

    def age_days(self) -> int | None:
        """Days since ``as_of``, or ``None`` if it is missing or unparseable.

        Never raises: a catalog with a malformed date should warn about being
        unparseable, not crash the command that was about to tell the user
        their prices might be stale.
        """
        if not self.as_of:
            return None
        try:
            from datetime import date  # noqa: PLC0415

            parsed = date.fromisoformat(self.as_of[:10])
        except ValueError:
            return None
        return (date.today() - parsed).days

    def is_stale(self, after_days: int | None = None) -> bool:
        age = self.age_days()
        return age is not None and age > (after_days or self.STALE_AFTER_DAYS)

    def merge_file(self, path: str | Path) -> None:
        """Merge a project pricing file over the shipped catalog."""
        try:
            data = load_structured(path)
        except ArenaError as exc:
            raise ConfigError(f"pricing file: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"pricing file {path} must be a mapping")

        models = data.get("models", data)
        if not isinstance(models, dict):
            raise ConfigError(f"pricing file {path}: 'models' must be a mapping")
        for model_id, entry in models.items():
            if model_id in ("as_of", "note", "notes", "currency", "aliases"):
                continue
            if not isinstance(entry, dict):
                raise ConfigError(f"pricing file {path}: models.{model_id} must be a mapping")
            self._merge_entry(str(model_id), entry)

        if isinstance(data.get("aliases"), dict):
            self._aliases.update({str(k): str(v) for k, v in data["aliases"].items()})
        self._cache.clear()

    def merge_overrides(self, model_id: str, card: dict[str, Any]) -> None:
        """Apply a single model's inline ``card:`` block."""
        if card:
            self._merge_entry(model_id, card)
            self._cache.pop(model_id, None)

    def _merge_entry(self, model_id: str, entry: dict[str, Any]) -> None:
        """Layer one override on top of any earlier override for the same model.

        The shipped catalog is *not* mixed in here — :meth:`_resolve` already
        layers it underneath at lookup time. Folding it in again would let the
        catalog overwrite a price the project had already overridden, so a
        second override silently reverted the first.
        """
        merged = dict(self._overrides.get(model_id) or {})
        merged.update(_canonical_keys(entry))
        self._overrides[model_id] = merged

    # ---- lookup -------------------------------------------------------

    def get(self, model_id: str, provider: str | None = None) -> ModelCard:
        """Look up a card. ``provider`` supplies a fallback for model families
        we cannot enumerate — every locally-hosted model shares the same
        cost and privacy facts, whatever it is called."""
        cache_key = f"{provider}:{model_id}" if provider else model_id
        if cache_key in self._cache:
            return self._cache[cache_key]

        entry, matched = self._resolve(model_id)
        if entry is None and provider:
            entry, matched = self._resolve(provider)

        card = _build_card(model_id, entry, default_as_of=self.as_of)
        card.known = entry is not None
        inherited = [name for name in matched if name != model_id]
        if inherited:
            card.notes = (card.notes + f" (inherits from '{inherited[0]}')").strip()
        self._cache[cache_key] = card
        return card

    def _resolve(self, model_id: str) -> tuple[dict[str, Any] | None, list[str]]:
        """Layer every matching entry, broadest first, so a narrow override
        (``mock:frontier``) inherits the general card (``mock``) instead of
        replacing it wholesale."""
        merged: dict[str, Any] = {}
        matched: list[str] = []
        for candidate in reversed(self._candidates(model_id)):
            for source in (self._entries, self._overrides):
                entry = source.get(candidate)
                if entry:
                    merged.update(entry)
                    if candidate not in matched:
                        matched.append(candidate)
        if not merged:
            return None, []
        return merged, matched

    def _candidates(self, model_id: str) -> list[str]:
        """Progressively looser forms of a model id, most specific first."""
        seen: list[str] = []

        def add(value: str) -> None:
            if value and value not in seen:
                seen.append(value)

        add(model_id)
        add(self._aliases.get(model_id, ""))

        bare = model_id
        for prefix in _PROVIDER_PREFIXES:
            if bare.startswith(prefix):
                bare = bare[len(prefix) :]
                add(bare)
                add(self._aliases.get(bare, ""))
                break

        # mock:oracle -> mock ; claude-opus-4-5@20251101 -> claude-opus-4-5
        for separator in (":", "@"):
            if separator in bare:
                add(bare.split(separator, 1)[0])

        # claude-haiku-4-5-20251001 -> claude-haiku-4-5
        parts = bare.split("-")
        if len(parts) > 1 and parts[-1].isdigit() and len(parts[-1]) == 8:
            add("-".join(parts[:-1]))
        return seen

    # ---- reporting ----------------------------------------------------

    def known_models(self) -> list[str]:
        return sorted(set(self._entries) | set(self._overrides))


def _build_card(model_id: str, entry: dict[str, Any] | None, default_as_of: str) -> ModelCard:
    entry = entry or {}

    features = entry.get("features") or []
    if isinstance(features, str):
        features = [features]
    normalized_features = {FEATURE_ALIASES.get(str(f), str(f)) for f in features}

    privacy_raw = entry.get("privacy") or {}
    privacy: dict[str, bool] = {}
    if isinstance(privacy_raw, dict):
        for key, value in privacy_raw.items():
            privacy[PRIVACY_ALIASES.get(str(key), str(key))] = bool(value)
    elif isinstance(privacy_raw, (list, tuple)):
        # A bare list means "these are all true".
        for key in privacy_raw:
            privacy[PRIVACY_ALIASES.get(str(key), str(key))] = True

    return ModelCard(
        model=model_id,
        provider=entry.get("provider"),
        display_name=entry.get("display_name"),
        input_usd_per_mtok=_opt_float(entry.get("input_usd_per_mtok", entry.get("input"))),
        output_usd_per_mtok=_opt_float(entry.get("output_usd_per_mtok", entry.get("output"))),
        cache_read_usd_per_mtok=_opt_float(entry.get("cache_read_usd_per_mtok")),
        cache_write_usd_per_mtok=_opt_float(entry.get("cache_write_usd_per_mtok")),
        context_tokens=_opt_int(entry.get("context_tokens", entry.get("context_window"))),
        max_output_tokens=_opt_int(entry.get("max_output_tokens")),
        features=normalized_features,
        privacy=privacy,
        notes=str(entry.get("notes", "")),
        as_of=str(entry.get("as_of", default_as_of)),
    )


#: Short spellings accepted in project pricing files, mapped to the canonical
#: key. Normalised on the way in, so a catalog entry's canonical key can never
#: shadow an override that used the alias.
_KEY_ALIASES = {
    "input": "input_usd_per_mtok",
    "output": "output_usd_per_mtok",
    "context_window": "context_tokens",
    "context": "context_tokens",
    "max_output": "max_output_tokens",
}


def _canonical_keys(entry: dict[str, Any]) -> dict[str, Any]:
    return {_KEY_ALIASES.get(str(key), str(key)): value for key, value in entry.items()}


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"expected a number in the model card, got {value!r}") from exc


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"expected an integer in the model card, got {value!r}") from exc


def _load_catalog() -> dict[str, Any]:
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - packaging bug
        raise ArenaError(f"could not read the bundled model catalog: {exc}") from exc


def build_price_book(config: Any) -> PriceBook:
    """Assemble the price book for a loaded :class:`ProjectConfig`."""
    book = PriceBook()
    pricing_path = getattr(config, "pricing_path", None)
    if pricing_path:
        book.merge_file(config.resolve(pricing_path))
    for model_id, entry in (getattr(config, "pricing_overrides", None) or {}).items():
        book.merge_overrides(str(model_id), entry)
    for spec in getattr(config, "models", []):
        if spec.card:
            book.merge_overrides(spec.model, spec.card)
    return book
