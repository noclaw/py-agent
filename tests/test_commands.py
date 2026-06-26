"""Slash commands: built-ins, dispatch, and custom markdown commands."""

from __future__ import annotations

import io

from rich.console import Console

from agent.commands import (
    CommandContext,
    build_registry,
    load_markdown_commands,
)
from agent.model import Model
from agent.models_registry import ModelInfo
from agent.permissions import PermissionMode, Permissions
from agent.tools import coding_tools
from agent.types import user_message


def _ctx(cwd=".", history=None, permissions=None):
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=200)
    registry = build_registry(cwd)
    # client=None is fine: the commands only read/mutate provider/model strings.
    model = Model(provider="anthropic", model="claude-sonnet-4-6")
    ctx = CommandContext(
        console=console,
        history=history if history is not None else [],
        tools=coding_tools("."),
        permissions=permissions or Permissions(),
        model=model,
        registry=registry,
    )
    return ctx, buffer, registry


def test_unknown_command():
    ctx, buf, registry = _ctx()
    out = registry.dispatch("/nope", ctx)
    assert out.prompt is None and out.exit is False
    assert "Unknown command" in buf.getvalue()


def test_clear_empties_history():
    ctx, buf, registry = _ctx(history=[user_message("hi")])
    registry.dispatch("/clear", ctx)
    assert ctx.history == []


def test_exit():
    ctx, buf, registry = _ctx()
    assert registry.dispatch("/exit", ctx).exit is True
    assert registry.dispatch("/quit", ctx).exit is True


def test_help_lists_commands():
    ctx, buf, registry = _ctx()
    registry.dispatch("/help", ctx)
    out = buf.getvalue()
    assert "/help" in out and "/model" in out and "/tools" in out


def test_tools_lists_tool_names():
    ctx, buf, registry = _ctx()
    registry.dispatch("/tools", ctx)
    out = buf.getvalue()
    assert "read" in out and "bash" in out and "grep" in out


def test_model_switch():
    ctx, buf, registry = _ctx()
    registry.dispatch("/model anthropic/claude-opus-4-8", ctx)
    assert ctx.model.name == "anthropic/claude-opus-4-8"
    registry.dispatch("/model claude-haiku-4-5", ctx)  # keep provider
    assert ctx.model.name == "anthropic/claude-haiku-4-5"


def test_model_switch_to_custom_sets_spec():
    ctx, buf, registry = _ctx()
    spec = {"id": "qwen3", "provider": "local", "api": "openai-completions", "baseUrl": "x"}
    ctx.models = [ModelInfo(provider="local", id="qwen3", spec=spec, source="user")]
    registry.dispatch("/model local/qwen3", ctx)
    assert ctx.model.name == "local/qwen3"
    assert ctx.model._spec == spec  # the full spec is what gets streamed


def test_model_picker_no_args(monkeypatch):
    ctx, buf, registry = _ctx()
    spec = {"id": "qwen3", "provider": "local"}
    ctx.models = [
        ModelInfo(provider="anthropic", id="claude-opus-4-8"),
        ModelInfo(provider="local", id="qwen3", spec=spec),
    ]
    import agent.picker

    monkeypatch.setattr(agent.picker, "select", lambda *a, **k: "local/qwen3")
    registry.dispatch("/model", ctx)
    assert ctx.model.name == "local/qwen3" and ctx.model._spec == spec


def test_model_picker_cancel_leaves_unchanged(monkeypatch):
    ctx, buf, registry = _ctx()
    ctx.models = [ModelInfo(provider="anthropic", id="claude-opus-4-8")]
    import agent.picker

    monkeypatch.setattr(agent.picker, "select", lambda *a, **k: None)
    registry.dispatch("/model", ctx)
    assert ctx.model.name == "anthropic/claude-sonnet-4-6"  # unchanged
    assert "unchanged" in buf.getvalue()


def test_checkpoints_and_rewind(tmp_path):
    from agent.checkpoints import Checkpoints

    f = tmp_path / "f.txt"
    f.write_text("v1")
    cps = Checkpoints()
    cps.stash("c1", "edit", f)
    cps.commit("c1", success=True)
    f.write_text("v2")  # the simulated edit

    ctx, buf, registry = _ctx(cwd=str(tmp_path))
    ctx.checkpoints = cps

    registry.dispatch("/checkpoints", ctx)
    out = buf.getvalue()
    assert "checkpoints (1)" in out and "f.txt" in out

    registry.dispatch("/rewind", ctx)  # no arg → undo last
    assert f.read_text() == "v1" and len(cps) == 0


def test_rewind_with_no_checkpoints():
    ctx, buf, registry = _ctx()
    registry.dispatch("/rewind", ctx)
    assert "nothing to rewind" in buf.getvalue()


def test_mode_change_and_invalid():
    ctx, buf, registry = _ctx()
    registry.dispatch("/mode plan", ctx)
    assert ctx.permissions.mode is PermissionMode.PLAN
    registry.dispatch("/mode bogus", ctx)
    assert "Unknown mode" in buf.getvalue()
    assert ctx.permissions.mode is PermissionMode.PLAN  # unchanged


# --- custom markdown commands ---------------------------------------------


def _write_command(tmp_path, name, body):
    cmd_dir = tmp_path / ".pya" / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    (cmd_dir / f"{name}.md").write_text(body)
    return cmd_dir


def test_markdown_command_expands_arguments(tmp_path):
    _write_command(
        tmp_path,
        "review",
        "---\ndescription: Review a file\nargument-hint: <path>\n---\nReview the file $1 and summarize $ARGUMENTS.",
    )
    ctx, buf, registry = _ctx(cwd=tmp_path)
    cmd = registry.get("review")
    assert cmd is not None and cmd.custom and cmd.description == "Review a file"
    assert cmd.argument_hint == "<path>"

    out = registry.dispatch("/review foo.py thoroughly", ctx)
    assert out.prompt == "Review the file foo.py and summarize foo.py thoroughly."


def test_markdown_command_without_frontmatter(tmp_path):
    _write_command(tmp_path, "hi", "Just say hello.")
    ctx, buf, registry = _ctx(cwd=tmp_path)
    out = registry.dispatch("/hi", ctx)
    assert out.prompt == "Just say hello."


def test_builtin_wins_over_custom_with_same_name(tmp_path):
    _write_command(tmp_path, "help", "custom help override")
    registry = build_registry(tmp_path)
    assert registry.get("help").custom is False  # built-in preserved


def test_load_markdown_namespaces_subdirs(tmp_path):
    cmd_dir = tmp_path / ".pya" / "commands" / "git"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "pr.md").write_text("Open a PR.")
    commands = load_markdown_commands([tmp_path / ".pya" / "commands"])
    assert any(c.name == "git:pr" for c in commands)
