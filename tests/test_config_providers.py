"""Tests for the ``providers:`` and ``budgets:`` config blocks.

These blocks are the reason v2 exists, so two things need protecting:

* **that every config written before they existed still behaves identically.**
  The 2.0 promise is that the new blocks are additive; a regression here breaks
  every project anyone already has, and the four example projects are the
  canaries because CI runs them end to end.
* **that a profile never carries a credential value.** ``to_dict`` is what the
  browser API serialises, so a secret that survives that call is a secret on
  the wire.

The capability tests below (two profiles, same vendor, one run) exist because
that combination was impossible in v1 and is the headline reason to upgrade.
"""

from __future__ import annotations

import pytest

from agent_arena.core.config import BudgetSettings, ProjectConfig, ProviderSpec, load_config
from agent_arena.core.errors import ConfigError

EXAMPLES = ("support_triage", "doc_extraction", "pipeline_demo", "local_demo")


def build(**overrides) -> ProjectConfig:
    data = {"project": "t", "models": [{"key": "m", "model": "mock:small"}], **overrides}
    return ProjectConfig.from_dict(data, root="projects/support_triage")


# ------------------------------------------------------------ back-compat


@pytest.mark.parametrize("name", EXAMPLES)
def test_a_config_written_before_providers_existed_is_unchanged(name):
    config = load_config(f"projects/{name}")
    assert config.providers == []
    assert config.budgets.max_run_usd is None
    assert config.budgets.on_exceed == "stop"
    # Every model still routes through the v1 vendor path.
    assert all(config.provider_for(spec) is None for spec in config.models)


def test_a_bare_vendor_kind_still_means_what_it_meant_in_v1():
    # `provider: anthropic` is v1 syntax for "use the Anthropic connector",
    # not a reference to a declared profile. Returning None keeps the existing
    # registry in charge of it.
    config = build(models=[{"key": "c", "model": "claude-sonnet-5", "provider": "anthropic"}])
    assert config.provider_for(config.models[0]) is None


# ------------------------------------------------------------- the profile


def test_a_profile_parses_every_field_it_advertises():
    config = build(
        providers=[
            {
                "id": "gw",
                "kind": "openai_compatible",
                "base_url": "https://gateway.corp.internal/v1",
                "api_key": "${keyring:agent-arena/corp}",
                "headers": {"X-Portkey-Config": "cfg_abc"},
                "timeout_s": 60,
                "verify_tls": "/etc/ssl/corp-ca.pem",
                "proxy": "http://squid.corp:3128",
                "model_prefix": "openai/",
                "rate_limit": {"rpm": 500, "tpm": 200000, "concurrency": 4},
                "retry": {"attempts": 3, "jitter": True},
            }
        ]
    )
    profile = config.providers[0]
    assert profile.id == "gw"
    assert profile.base_url == "https://gateway.corp.internal/v1"
    assert profile.headers["X-Portkey-Config"] == "cfg_abc"
    assert profile.verify_tls == "/etc/ssl/corp-ca.pem"
    assert profile.proxy == "http://squid.corp:3128"
    assert profile.model_prefix == "openai/"
    assert profile.rate_limit["rpm"] == 500
    assert profile.retry["attempts"] == 3


def test_api_key_and_api_key_ref_are_the_same_field():
    # `api_key:` is what someone naturally writes in YAML; `api_key_ref:` is
    # what the field is really called. Accepting one spelling only would be a
    # silent no-op for half the people who try it.
    a = ProviderSpec.parse({"id": "a", "kind": "openai", "api_key": "${env:K}"}, 0)
    b = ProviderSpec.parse({"id": "b", "kind": "openai", "api_key_ref": "${env:K}"}, 1)
    assert a.api_key_ref == b.api_key_ref == "${env:K}"


def test_to_dict_carries_the_reference_and_never_a_value(monkeypatch):
    monkeypatch.setenv("ARENA_PROFILE_KEY", "sk-ant-not-a-real-key-0001")
    profile = ProviderSpec.parse(
        {"id": "p", "kind": "openai", "api_key": "${env:ARENA_PROFILE_KEY}"}, 0
    )
    rendered = str(profile.to_dict())
    assert "${env:ARENA_PROFILE_KEY}" in rendered
    assert "sk-ant-not-a-real-key-0001" not in rendered


def test_a_profile_needs_an_id_and_a_kind():
    with pytest.raises(ConfigError, match="providers"):
        ProviderSpec.parse({"kind": "openai"}, 0)
    with pytest.raises(ConfigError, match="providers"):
        ProviderSpec.parse({"id": "p"}, 0)


def test_an_unknown_kind_lists_the_kinds_that_work():
    with pytest.raises(ConfigError) as exc:
        ProviderSpec.parse({"id": "p", "kind": "opeanai"}, 0)
    message = str(exc.value)
    assert "opeanai" in message
    assert "openai" in message


def test_a_duplicate_profile_id_is_rejected():
    with pytest.raises(ConfigError, match="duplicate"):
        build(
            providers=[
                {"id": "same", "kind": "openai"},
                {"id": "same", "kind": "anthropic"},
            ]
        )


# --------------------------------------------------------------- the point


def test_two_keys_for_one_vendor_can_compete_in_the_same_run():
    """The capability the whole block exists for, impossible in v1."""
    config = build(
        providers=[
            {"id": "work", "kind": "openai", "api_key": "${env:WORK_KEY}"},
            {"id": "personal", "kind": "openai", "api_key": "${keyring:agent-arena/personal}"},
        ],
        models=[
            {"key": "gpt5_work", "provider": "work", "model": "gpt-5"},
            {"key": "gpt5_personal", "provider": "personal", "model": "gpt-5"},
        ],
    )
    resolved = {spec.key: config.provider_for(spec) for spec in config.models}
    assert resolved["gpt5_work"].id == "work"
    assert resolved["gpt5_personal"].id == "personal"
    # Same model id, same vendor, two different credentials.
    assert config.models[0].model == config.models[1].model
    assert resolved["gpt5_work"].api_key_ref != resolved["gpt5_personal"].api_key_ref


def test_a_model_pointing_at_a_profile_that_does_not_exist_is_caught_at_load():
    with pytest.raises(ConfigError):
        build(
            providers=[{"id": "work", "kind": "openai"}],
            models=[{"key": "m", "provider": "typo", "model": "gpt-5"}],
        )


# ----------------------------------------------------------------- budgets


def test_budgets_parse():
    config = build(
        budgets={
            "max_run_usd": 5.0,
            "max_model_usd": 2.0,
            "confirm_above_usd": 1.0,
            "on_exceed": "warn",
        }
    )
    assert config.budgets == BudgetSettings(5.0, 2.0, 1.0, "warn")


def test_a_missing_budgets_block_gates_nothing():
    # None means "no cap", which is what every existing config must keep meaning.
    assert build().budgets.max_run_usd is None


def test_a_negative_cap_is_rejected():
    with pytest.raises(ConfigError, match="budgets"):
        build(budgets={"max_run_usd": -1.0})


def test_an_unknown_on_exceed_lists_the_valid_actions():
    with pytest.raises(ConfigError) as exc:
        build(budgets={"on_exceed": "explode"})
    assert "stop" in str(exc.value)
