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
    assert args.provider == "anthropic"
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
