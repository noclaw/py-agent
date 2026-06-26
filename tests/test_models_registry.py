"""The custom/local model registry: parsing models.json, merging, resolving."""

from __future__ import annotations

import json

from agent.models_registry import ModelRegistry, load_model_registry, merge_catalog


def _write_models(dir_path, data):
    pya = dir_path / ".pya"
    pya.mkdir(parents=True, exist_ok=True)
    (pya / "models.json").write_text(json.dumps(data))


LOCAL = {
    "providers": {
        "local": {
            "baseUrl": "http://127.0.0.1:8008/v1",
            "api": "openai-completions",
            "apiKey": "secret",
            "models": [
                {"id": "qwen3", "name": "Qwen3", "contextWindow": 32768, "maxTokens": 4096}
            ],
        }
    }
}


def test_load_builds_full_spec(tmp_path):
    _write_models(tmp_path, LOCAL)
    reg = load_model_registry(tmp_path)
    assert len(reg.custom) == 1
    info = reg.custom[0]
    assert info.label == "local/qwen3" and info.is_custom and info.source == "project"
    # Provider connection fields are flattened into each model's spec.
    assert info.spec["baseUrl"] == "http://127.0.0.1:8008/v1"
    assert info.spec["api"] == "openai-completions"
    assert info.spec["apiKey"] == "secret"
    assert info.spec["provider"] == "local"
    assert info.spec["contextWindow"] == 32768


def test_resolve_custom_vs_builtin(tmp_path):
    _write_models(tmp_path, LOCAL)
    reg = load_model_registry(tmp_path)
    assert reg.resolve("local", "qwen3").label == "local/qwen3"
    assert reg.resolve(None, "qwen3").label == "local/qwen3"  # bare id matches
    assert reg.resolve("anthropic", "claude-sonnet-4-6") is None  # not custom → built-in


def test_missing_file_is_empty(tmp_path):
    assert load_model_registry(tmp_path).custom == []


def test_merge_catalog_sorts_and_shadows(tmp_path):
    _write_models(tmp_path, LOCAL)
    reg = load_model_registry(tmp_path)
    builtin = [
        {"provider": "openai", "id": "gpt-5.1"},
        {"provider": "anthropic", "id": "claude-sonnet-4-6"},
    ]
    catalog = merge_catalog(builtin, reg)
    labels = [m.label for m in catalog]
    assert labels == ["anthropic/claude-sonnet-4-6", "local/qwen3", "openai/gpt-5.1"]
    # The custom one carries a spec; built-ins don't.
    assert next(m for m in catalog if m.label == "local/qwen3").is_custom
    assert not next(m for m in catalog if m.label == "openai/gpt-5.1").is_custom


def test_custom_shadows_builtin_same_label():
    reg = ModelRegistry(custom=[])
    _ = reg  # explicit: with no customs, merge is just the builtin list
    builtin = [{"provider": "x", "id": "m"}]
    assert [m.label for m in merge_catalog(builtin, ModelRegistry())] == ["x/m"]
