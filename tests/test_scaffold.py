"""Scaffold checks: the package imports, the CLI parses, the provider layer is present."""

from __future__ import annotations

import pytest

import agent
from agent.cli import _build_parser, main


def test_version_is_exposed():
    assert isinstance(agent.__version__, str)
    assert agent.__version__


def test_provider_layer_is_importable():
    # The native provider layer (httpx, no Node/SDK) backs the model calls.
    from agent.providers import AnthropicProvider, OpenAICompatProvider  # noqa: F401


def test_cli_parser_defaults():
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.command is None
    assert args.provider is None  # resolved from settings/defaults in main()
    assert args.prompt is None  # REPL by default
    assert args.cwd == "."


def test_cli_parses_one_shot_flags():
    parser = _build_parser()
    args = parser.parse_args(["-p", "hello", "--cwd", "/tmp", "--reasoning", "low"])
    assert args.prompt == "hello"
    assert args.cwd == "/tmp"
    assert args.reasoning == "low"


def test_cli_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "pya" in capsys.readouterr().out


def test_auth_set_list_remove(tmp_path, monkeypatch, capsys):
    from agent.providers import oauth

    monkeypatch.setattr(oauth, "TOKEN_STORE", tmp_path / "auth.json")
    assert main(["auth", "set", "openai", "--key", "sk-test-key"]) == 0
    assert oauth.get_api_key("openai") == "sk-test-key"
    capsys.readouterr()

    assert main(["auth", "list"]) == 0
    assert "openai" in capsys.readouterr().out

    assert main(["auth", "remove", "openai"]) == 0
    assert oauth.get_api_key("openai") is None


def test_config_commands(tmp_path, monkeypatch, capsys):
    from agent import settings as settings_mod

    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "settings.toml")
    assert main(["config", "set-default", "anthropic/claude-opus-4-8"]) == 0
    assert main(["config", "models", "openai", "gpt-5.1", "gpt-5-codex"]) == 0

    s = settings_mod.load()
    assert (s.default_provider, s.default_model) == ("anthropic", "claude-opus-4-8")
    assert s.providers["openai"].models == ("gpt-5.1", "gpt-5-codex")

    capsys.readouterr()
    assert main(["config", "show"]) == 0
    assert "openai" in capsys.readouterr().out

    assert main(["config", "remove-provider", "openai"]) == 0
    assert "openai" not in settings_mod.load().providers


def test_config_set_scalars(tmp_path, monkeypatch):
    from agent import settings as settings_mod

    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "settings.toml")
    assert main(["config", "set", "max_retries", "5"]) == 0
    assert main(["config", "set", "compact", "false"]) == 0
    assert main(["config", "set", "permission_mode", "acceptEdits"]) == 0
    s = settings_mod.load()
    assert s.max_retries == 5 and s.compact is False and s.permission_mode == "acceptEdits"

    assert main(["config", "set", "reasoning", "bogus"]) == 1   # invalid value rejected
    assert main(["config", "set", "nope", "1"]) == 1            # unknown key rejected

    assert main(["config", "unset", "max_retries"]) == 0
    assert settings_mod.load().max_retries is None
