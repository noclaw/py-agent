"""User settings (~/.pya/settings.toml): parsing, allowlist, defaults, key resolution."""

from __future__ import annotations

import pytest

from agent import settings as settings_mod
from agent.providers import auth
from agent.providers.catalog import KNOWN_PROVIDERS

SAMPLE = """
default = "anthropic/claude-opus-4-8"

[providers.anthropic]
api_key = "sk-ant-test"
models = ["claude-opus-4-8", "claude-sonnet-4-6"]

[providers.openai]
api_key = "sk-openai-test"
"""


def _write(tmp_path, text):
    p = tmp_path / "settings.toml"
    p.write_text(text)
    return p


def test_load_parses_default_and_providers(tmp_path):
    s = settings_mod.load(_write(tmp_path, SAMPLE))
    assert s.configured
    assert (s.default_provider, s.default_model) == ("anthropic", "claude-opus-4-8")
    assert s.api_key("anthropic") == "sk-ant-test"
    assert s.api_key("openai") == "sk-openai-test"
    assert s.api_key("groq") is None


def test_model_list_allowlist_and_builtin_fallback(tmp_path):
    s = settings_mod.load(_write(tmp_path, SAMPLE))
    rows = s.model_list()
    anthropic = [r["id"] for r in rows if r["provider"] == "anthropic"]
    openai = [r["id"] for r in rows if r["provider"] == "openai"]
    # anthropic: exactly the allowlist; openai (no list): the curated built-ins for openai.
    assert anthropic == ["claude-opus-4-8", "claude-sonnet-4-6"]
    assert "gpt-5.1" in openai and len(openai) > 1
    # A provider not listed never appears.
    assert not any(r["provider"] == "groq" for r in rows)


def test_missing_file_is_empty(tmp_path):
    s = settings_mod.load(tmp_path / "nope.toml")
    assert not s.configured and s.default_model is None


def test_invalid_toml_is_empty(tmp_path):
    s = settings_mod.load(_write(tmp_path, "this = = not toml"))
    assert not s.configured


def test_save_roundtrips(tmp_path):
    path = tmp_path / "out.toml"
    original = settings_mod.load(_write(tmp_path, SAMPLE))
    settings_mod.save(original, path)
    reloaded = settings_mod.load(path)
    assert (reloaded.default_provider, reloaded.default_model) == ("anthropic", "claude-opus-4-8")
    assert reloaded.api_key("anthropic") == "sk-ant-test"
    assert reloaded.providers["anthropic"].models == ("claude-opus-4-8", "claude-sonnet-4-6")
    assert reloaded.providers["openai"].models == ()


def test_catalog_models_scopes_to_configured(tmp_path, monkeypatch):
    from agent.providers import oauth

    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", _write(tmp_path, SAMPLE))
    monkeypatch.setattr(oauth, "TOKEN_STORE", tmp_path / "auth.json")
    rows = settings_mod.catalog_models()
    providers = {r["provider"] for r in rows}
    assert providers == {"anthropic", "openai"}  # only configured providers
    assert [r["id"] for r in rows if r["provider"] == "anthropic"] == ["claude-opus-4-8", "claude-sonnet-4-6"]


def test_catalog_models_includes_keyed_provider(tmp_path, monkeypatch):
    from agent.providers import oauth

    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "none.toml")  # no settings
    monkeypatch.setattr(oauth, "TOKEN_STORE", tmp_path / "auth.json")
    oauth.set_api_key("openai", "sk-x")
    rows = settings_mod.catalog_models()
    assert {r["provider"] for r in rows} == {"openai"}  # only the key-stored provider
    assert any(r["id"] == "gpt-5.1" for r in rows)


def test_catalog_models_falls_back_to_all_builtins(tmp_path, monkeypatch):
    from agent.providers import oauth
    from agent.providers.catalog import builtin_models

    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "none.toml")
    monkeypatch.setattr(oauth, "TOKEN_STORE", tmp_path / "auth.json")
    assert settings_mod.catalog_models() == builtin_models()


def test_resolve_api_key_uses_settings_when_no_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", _write(tmp_path, SAMPLE))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    route = KNOWN_PROVIDERS["anthropic"]
    assert auth.resolve_api_key(route, None, provider="anthropic") == "sk-ant-test"


def test_env_overrides_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", _write(tmp_path, SAMPLE))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-wins")
    route = KNOWN_PROVIDERS["anthropic"]
    assert auth.resolve_api_key(route, None, provider="anthropic") == "sk-env-wins"


def test_spec_key_wins_over_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", _write(tmp_path, SAMPLE))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    route = KNOWN_PROVIDERS["anthropic"]
    assert auth.resolve_api_key(route, {"apiKey": "sk-spec"}, provider="anthropic") == "sk-spec"


def test_stored_key_beats_settings_but_env_beats_stored(tmp_path, monkeypatch):
    from agent.providers import oauth

    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", _write(tmp_path, SAMPLE))  # settings: sk-ant-test
    monkeypatch.setattr(oauth, "TOKEN_STORE", tmp_path / "auth.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    oauth.set_api_key("anthropic", "sk-stored")
    route = KNOWN_PROVIDERS["anthropic"]
    # `pya auth set` (auth.json) beats the hand-edited settings.toml key…
    assert auth.resolve_api_key(route, None, provider="anthropic") == "sk-stored"
    # …but an env var still overrides everything below the spec key.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert auth.resolve_api_key(route, None, provider="anthropic") == "sk-env"
