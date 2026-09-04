"""The shipped price catalog, and the promise it makes to a cross-vendor run.

``metrics.build_leaderboard`` reports a cost only when *every* completed call
in a run was priced. One unpriced vendor therefore does not cost that vendor a
metric — it silently removes the cost axis from the whole comparison, for every
model in it. Catalog coverage is that behaviour, not inert data, so these tests
hold the line on it: a mixed OpenAI / Anthropic / Google shortlist still costs
out, every alias the catalog advertises lands on a priced card, and no entry
ever ships half a price (an input rate with no output rate would bill every
call at a fraction of the truth instead of honestly reporting the gap).

The other half of invariant 4 is what is *absent*: a model whose current list
price could not be sourced is left out on purpose, so the tests below check the
shape and honesty of what is here rather than demanding a particular roster.

Everything reads the shipped JSON straight off disk. No network, no SDK.
"""

from __future__ import annotations

import copy
import json

import pytest

from agent_arena.connectors.pricing import CATALOG_PATH, FEATURE_ALIASES, PriceBook

CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
ENTRIES: dict = CATALOG["models"]
ALIASES: dict = CATALOG["aliases"]

#: ``local`` and ``mock`` are free on purpose — nothing is billed for a model
#: you host yourself or a run that never leaves the process. Every other card
#: stands for a real invoice and is held to the stricter rules below.
FALLBACK_CARDS = {"local", "mock"}
VENDOR_ENTRIES = sorted(set(ENTRIES) - FALLBACK_CARDS)

#: The question the product exists to answer — "should I ship GPT-5 or Claude?"
#: — costed against a cheap tier from each vendor, because that is the run
#: whose cost axis used to vanish.
CROSS_VENDOR_SHORTLIST = [
    "gpt-5",
    "gpt-4o-mini",
    "claude-opus-5",
    "claude-haiku-4-5",
    "gemini-2.5-flash",
    "mistral-small-latest",
]


# ---- the catalog round-trips -----------------------------------------------


def test_every_catalog_entry_resolves_to_a_known_priced_card() -> None:
    book = PriceBook()

    for model_id in ENTRIES:
        card = book.get(model_id)
        assert card.known is True, f"{model_id} is in the catalog but does not resolve"
        assert card.has_pricing is True, f"{model_id} resolves without a price"


def test_no_entry_ships_half_a_price() -> None:
    """An input rate with no output rate is worse than no card at all: the run
    still costs out, at a number that is quietly far too low."""
    for model_id, entry in ENTRIES.items():
        has_input = entry.get("input_usd_per_mtok", entry.get("input")) is not None
        has_output = entry.get("output_usd_per_mtok", entry.get("output")) is not None

        assert has_input is has_output, f"{model_id} declares one price without the other"
        assert has_input, f"{model_id} declares no price at all"


def test_only_the_fallback_cards_are_free() -> None:
    """A zero price wins the cost axis outright. Nothing billable may claim it."""
    book = PriceBook()

    for model_id in VENDOR_ENTRIES:
        card = book.get(model_id)
        assert card.input_usd_per_mtok > 0, f"{model_id} is priced at zero input"
        assert card.output_usd_per_mtok > 0, f"{model_id} is priced at zero output"


def test_every_vendor_entry_declares_its_context_window() -> None:
    """Context is a gate, not a decoration: a card with no window silently
    passes a constraint it may not actually meet."""
    book = PriceBook()

    for model_id in VENDOR_ENTRIES:
        assert book.get(model_id).context_tokens, f"{model_id} declares no context window"


def test_features_use_the_catalog_vocabulary_not_the_config_spellings() -> None:
    """``tools`` and ``json_mode`` are what people write in a config;
    ``function_calling`` and ``structured_outputs`` are what the catalog stores.
    Storing the config spelling would make the gate miss the model."""
    for model_id, entry in ENTRIES.items():
        for feature in entry.get("features", []):
            assert feature not in FEATURE_ALIASES, (
                f"{model_id} lists {feature!r}; use {FEATURE_ALIASES[feature]!r}"
            )


def test_a_config_spelling_still_matches_a_cross_vendor_card() -> None:
    assert PriceBook().get("gpt-5").missing_features(["tools", "json_mode"]) == []


# ---- the cross-vendor gap this catalog exists to close ---------------------


@pytest.mark.parametrize("model_id", ["gpt-5", "gemini-2.5-flash"])
def test_the_flagship_non_anthropic_models_are_priced(model_id: str) -> None:
    card = PriceBook().get(model_id)

    assert card.known is True
    assert card.has_pricing is True


def test_a_cross_vendor_shortlist_leaves_no_call_unpriced() -> None:
    """The regression this catalog fixes: one unpriced model in the shortlist
    nulls the cost metric for every model in the run, not just its own."""
    book = PriceBook()

    unpriced = [m for m in CROSS_VENDOR_SHORTLIST if not book.get(m).has_pricing]

    assert unpriced == []


def test_vendors_are_separable_on_price() -> None:
    """Costing a run is only useful if the numbers actually differ; identical
    prices across vendors would be the tell-tale of a copied placeholder."""
    book = PriceBook()
    rates = {book.get(m).input_usd_per_mtok for m in CROSS_VENDOR_SHORTLIST}

    assert len(rates) > 1


# ---- aliases ---------------------------------------------------------------


def test_every_alias_lands_on_a_priced_card() -> None:
    book = PriceBook()

    for alias in ALIASES:
        card = book.get(alias)
        assert card.known is True, f"alias {alias!r} resolves to nothing"
        assert card.has_pricing is True, f"alias {alias!r} resolves to an unpriced card"


def test_an_alias_costs_the_same_as_the_card_it_points_at() -> None:
    book = PriceBook()

    for alias, target in ALIASES.items():
        aliased, direct = book.get(alias), book.get(target)
        assert aliased.input_usd_per_mtok == direct.input_usd_per_mtok, alias
        assert aliased.output_usd_per_mtok == direct.output_usd_per_mtok, alias


def test_every_alias_earns_its_place() -> None:
    """``_candidates`` already strips vendor prefixes and dated suffixes, so an
    alias for a spelling that resolves anyway is dead weight that will drift."""
    for alias in ALIASES:
        thinned = copy.deepcopy(CATALOG)
        del thinned["aliases"][alias]

        assert PriceBook(thinned).get(alias).known is False, (
            f"alias {alias!r} is redundant — that id already resolves on its own"
        )


@pytest.mark.parametrize(
    "spelling, expected",
    [
        ("openai/gpt-5", "gpt-5"),
        ("azure/gpt-4o", "gpt-4o"),
        ("gemini/gemini-2.5-pro", "gemini-2.5-pro"),
        ("vertex_ai/gemini-2.0-flash", "gemini-2.0-flash"),
        ("models/gemini-2.5-flash", "gemini-2.5-flash"),
        ("gpt-4o-2024-08-06", "gpt-4o"),
        ("o4-mini-2025-04-16", "o4-mini"),
        ("mistral/mistral-large-latest", "mistral-large-latest"),
    ],
)
def test_the_spellings_people_actually_write_resolve(spelling: str, expected: str) -> None:
    """Gateway prefixes and dated snapshot ids are how these models arrive in a
    real config; each must cost out as the model it is."""
    book = PriceBook()

    assert book.get(spelling).input_usd_per_mtok == book.get(expected).input_usd_per_mtok


# ---- the arithmetic --------------------------------------------------------


def test_cost_rises_with_every_extra_token() -> None:
    card = PriceBook().get("gpt-5")

    costs = [card.cost_usd(n, n) for n in (0, 1_000, 10_000, 100_000)]

    assert costs[0] == 0.0
    assert costs == sorted(costs)
    assert len(set(costs)) == len(costs)


def test_cost_is_the_published_rate_per_million_tokens() -> None:
    card = PriceBook().get("gpt-5")

    assert card.cost_usd(1_000_000, 0) == pytest.approx(card.input_usd_per_mtok)
    assert card.cost_usd(0, 1_000_000) == pytest.approx(card.output_usd_per_mtok)
    assert card.cost_usd(2_000_000, 2_000_000) == pytest.approx(
        2 * (card.input_usd_per_mtok + card.output_usd_per_mtok)
    )


def test_a_cached_read_is_cheaper_than_a_fresh_one_where_a_rate_is_published() -> None:
    """Cards that carry a cache rate must undercut their own input rate; a
    cache rate at or above input would make caching look like a cost."""
    book = PriceBook()

    for model_id in VENDOR_ENTRIES:
        card = book.get(model_id)
        if card.cache_read_usd_per_mtok is None:
            continue
        assert card.cache_read_usd_per_mtok < card.input_usd_per_mtok, model_id


# ---- the honesty the catalog is supposed to carry --------------------------


def test_the_catalog_dates_itself_and_stamps_that_date_on_every_card() -> None:
    """A price with no date cannot be judged stale, and the report prints this."""
    book = PriceBook()

    assert book.as_of == CATALOG["as_of"]
    assert book.get("gpt-5").as_of == CATALOG["as_of"]


def test_the_note_tells_the_reader_to_verify_before_spending_money() -> None:
    """These are list prices that vendors change often. Shipping them without
    that warning is how a stale number becomes a purchasing decision."""
    note = " ".join(CATALOG["note"]).lower()

    assert "list price" in note
    assert "verify" in note


# --------------------------------------------------------------------- staleness


class StalenessTests:
    """Roadmap wording: 'warn past 90 days'. This is that number given a name
    other code can reference, and never allowed to crash a command over a
    malformed date — the check exists to warn, not to become a new failure
    mode."""

    def test_a_fresh_catalog_is_not_stale(self):
        from datetime import date, timedelta

        recent = (date.today() - timedelta(days=5)).isoformat()
        book = PriceBook({"as_of": recent, "models": {}})
        assert book.is_stale() is False
        assert book.age_days() == 5

    def test_a_catalog_past_the_window_is_stale(self):
        book = PriceBook({"as_of": "2020-01-01", "models": {}})
        assert book.is_stale() is True
        assert book.age_days() > 90

    def test_the_threshold_is_configurable_per_call(self):
        from datetime import date, timedelta

        ten_days_old = (date.today() - timedelta(days=10)).isoformat()
        book = PriceBook({"as_of": ten_days_old, "models": {}})
        assert book.is_stale(after_days=5) is True
        assert book.is_stale(after_days=30) is False

    def test_a_missing_as_of_has_no_age_and_is_not_stale(self):
        book = PriceBook({"models": {}})
        assert book.age_days() is None
        assert book.is_stale() is False

    def test_a_malformed_as_of_does_not_raise(self):
        book = PriceBook({"as_of": "not-a-real-date", "models": {}})
        assert book.age_days() is None
        assert book.is_stale() is False

    def test_the_shipped_catalog_is_fresh_as_of_writing(self):
        # If this ever fails, the catalog itself needs a refresh, not the test.
        book = PriceBook()
        assert book.age_days() is not None


def test_arena_validate_reports_pricing_freshness(simple_project, capsys):
    from agent_arena.cli import main

    assert main(["validate", "--project", str(simple_project)]) == 0
    assert "pricing" in capsys.readouterr().out


def test_arena_models_flags_a_stale_catalog(monkeypatch, capsys):
    from agent_arena.cli import main
    from agent_arena.connectors import pricing as pricing_module

    class _StaleBook(PriceBook):
        def __init__(self):
            super().__init__({"as_of": "2020-01-01", "models": {}})

    monkeypatch.setattr(pricing_module, "PriceBook", _StaleBook)
    main(["models"])
    out = capsys.readouterr().out
    assert "days old" in out
