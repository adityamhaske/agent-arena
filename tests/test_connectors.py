"""Provider resolution, the offline mock, and the model-card catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_arena.connectors import (
    GenerationRequest,
    MockConnector,
    PriceBook,
    build_connector,
    infer_provider,
    requires_api_key,
)
from agent_arena.core.config import ModelSpec
from agent_arena.core.errors import ConnectorError


def request(prompt: str = "hello", **metadata) -> GenerationRequest:
    return GenerationRequest(
        messages=[{"role": "user", "content": prompt}], metadata=metadata
    )


# ---- provider inference ----------------------------------------------------


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("claude-opus-5", "anthropic"),
        ("claude-haiku-4-5", "anthropic"),
        ("gpt-4o", "openai"),
        ("o3-mini", "openai"),
        ("gemini-2.5-flash", "gemini"),
        ("mock:oracle", "mock"),
        ("bedrock/anthropic.claude-opus-5", "litellm"),
        # Local runtimes route to the stdlib HTTP connector, not LiteLLM, so
        # evaluating a model on your own machine needs no SDK installed.
        ("ollama/llama3.3", "local"),
        ("local/my-finetune", "local"),
        ("llama3.2", "local"),
        ("qwen2.5-coder:7b", "local"),
        ("mistral-nemo", "local"),
    ],
)
def test_provider_is_inferred_from_the_model_id(model: str, provider: str) -> None:
    assert infer_provider(model) == provider


def test_unknown_model_id_asks_for_an_explicit_provider() -> None:
    with pytest.raises(ConnectorError, match="cannot infer a provider"):
        infer_provider("some-in-house-model")


def test_explicit_provider_wins_over_inference() -> None:
    spec = ModelSpec(key="k", model="claude-opus-5", provider="mock")
    assert build_connector(spec).provider == "mock"


def test_local_and_mock_models_need_no_credentials() -> None:
    assert requires_api_key(ModelSpec(key="k", model="mock:oracle")) is None
    assert requires_api_key(ModelSpec(key="k", model="llama3.2")) is None
    assert requires_api_key(ModelSpec(key="k", model="ollama/qwen2.5")) is None
    assert requires_api_key(ModelSpec(key="k", model="claude-opus-5")) == "ANTHROPIC_API_KEY"


def test_declared_env_var_that_is_unset_is_an_error() -> None:
    spec = ModelSpec(key="k", model="mock:oracle", api_key_env="DEFINITELY_NOT_SET_XYZ")
    with pytest.raises(ConnectorError, match="not set"):
        build_connector(spec)


# ---- the mock --------------------------------------------------------------


def test_oracle_mode_returns_the_reference() -> None:
    connector = MockConnector("mock:oracle")
    assert connector.generate(request(reference="expected")).text == "expected"


def test_oracle_answers_the_first_of_several_acceptable_references() -> None:
    connector = MockConnector("mock:oracle")
    assert connector.generate(request(reference=["refund", "billing"])).text == "refund"


def test_oracle_serialises_a_dict_reference_as_json() -> None:
    connector = MockConnector("mock:oracle")
    text = connector.generate(request(reference={"a": 1})).text
    assert json.loads(text) == {"a": 1}


def test_echo_and_fixed_modes() -> None:
    assert MockConnector("mock:echo").generate(request("ping")).text == "ping"
    fixed = MockConnector("mock:anything", mode="fixed", text="always this")
    assert fixed.generate(request()).text == "always this"


def test_flaky_mode_is_deterministic_for_the_same_test() -> None:
    connector = MockConnector("mock:flaky", mode="flaky", accuracy=50)
    first = connector.generate(request(reference="yes", test_id="t1", trial=1)).text
    second = connector.generate(request(reference="yes", test_id="t1", trial=1)).text

    assert first == second


def test_flaky_mode_hits_roughly_its_configured_accuracy() -> None:
    connector = MockConnector("mock:flaky", mode="flaky", accuracy=70)
    hits = sum(
        connector.generate(request(reference="yes", test_id=f"t{i}", trial=1)).text == "yes"
        for i in range(400)
    )
    assert 0.6 < hits / 400 < 0.8


def test_mode_can_be_given_in_params_so_the_suffix_is_free_for_labels() -> None:
    connector = MockConnector("mock:my-custom-label", mode="oracle")
    assert connector.generate(request(reference="ok")).text == "ok"


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ConnectorError, match="unknown mock mode"):
        MockConnector("mock:teleport")


def test_mock_reports_usage_and_latency() -> None:
    connector = MockConnector("mock:oracle", latency_ms=250)
    result = connector.generate(request(reference="a longer reference answer"))

    assert result.latency_ms == 250
    assert result.input_tokens > 0
    assert result.output_tokens > 0


# ---- model cards -----------------------------------------------------------


def test_catalog_prices_a_known_model() -> None:
    card = PriceBook().get("claude-opus-5")

    assert card.known is True
    assert card.input_usd_per_mtok == 5.0
    assert card.output_usd_per_mtok == 25.0
    assert card.context_tokens == 1_000_000


def test_cost_maths() -> None:
    card = PriceBook().get("claude-opus-5")
    # 1M in + 1M out at $5/$25
    assert card.cost_usd(1_000_000, 1_000_000) == pytest.approx(30.0)


def test_unknown_model_gets_no_price_rather_than_a_guess() -> None:
    card = PriceBook().get("some-model-we-never-heard-of")

    assert card.known is False
    assert card.has_pricing is False
    assert card.cost_usd(1000, 1000) is None


def test_dated_snapshot_ids_inherit_the_base_card() -> None:
    card = PriceBook().get("claude-haiku-4-5-20251001")

    assert card.input_usd_per_mtok == 1.0
    assert "inherits" in card.notes


def test_bedrock_prefixed_ids_resolve() -> None:
    assert PriceBook().get("anthropic.claude-opus-5").input_usd_per_mtok == 5.0


def test_overrides_layer_over_the_catalog_instead_of_replacing_it() -> None:
    book = PriceBook()
    book.merge_overrides("mock:custom", {"input_usd_per_mtok": 9.0})
    card = book.get("mock:custom")

    assert card.input_usd_per_mtok == 9.0                 # overridden
    assert "function_calling" in card.features            # inherited from `mock`
    assert card.privacy.get("on_prem") is True            # inherited


def test_project_pricing_file_is_merged(tmp_path: Path) -> None:
    path = tmp_path / "pricing.json"
    path.write_text(
        json.dumps({"models": {"claude-sonnet-5": {"input_usd_per_mtok": 2.0}}}),
        encoding="utf-8",
    )
    book = PriceBook()
    book.merge_file(path)

    assert book.get("claude-sonnet-5").input_usd_per_mtok == 2.0
    assert book.get("claude-sonnet-5").output_usd_per_mtok == 15.0   # untouched


def test_feature_aliases_are_normalised() -> None:
    book = PriceBook()
    book.merge_overrides("aliased", {"features": ["json_mode", "tools"]})
    card = book.get("aliased")

    assert card.missing_features(["structured_outputs", "function_calling"]) == []


def test_privacy_list_form_means_all_true() -> None:
    book = PriceBook()
    book.merge_overrides("listy", {"privacy": ["dpa", "zdr"]})
    card = book.get("listy")

    assert card.missing_privacy(["dpa", "zero_data_retention"]) == []


def test_documented_model_level_restriction_is_recorded() -> None:
    """Fable 5 cannot run under zero data retention — that is a model fact."""
    card = PriceBook().get("claude-fable-5")

    assert card.privacy.get("zero_data_retention") is False
    assert card.missing_privacy(["zdr"]) == ["zero_data_retention"]
