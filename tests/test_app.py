"""App-level wiring: the UserPromptSubmit hook seam in the REPL/one-shot path."""

from __future__ import annotations

from rich.console import Console

from agent.app import _apply_prompt_submit, _build_default_hooks
from agent.hooks import HookResult, Hooks, UserPromptSubmit


async def test_apply_prompt_submit_injects_context():
    hooks = Hooks()

    @hooks.user_prompt_submit()
    def add(event: UserPromptSubmit):
        return HookResult(additional_context="[ctx]")

    out = await _apply_prompt_submit(hooks, "do the thing", Console())
    assert out is not None
    assert out.startswith("do the thing")
    assert "[ctx]" in out


async def test_apply_prompt_submit_blocks_on_deny():
    hooks = Hooks()

    @hooks.user_prompt_submit()
    def block(event: UserPromptSubmit):
        return HookResult(decision="deny", reason="nope")

    out = await _apply_prompt_submit(hooks, "secret", Console())
    assert out is None  # blocked → caller skips the turn


async def test_apply_prompt_submit_passthrough_without_hooks():
    out = await _apply_prompt_submit(None, "unchanged", Console())
    assert out == "unchanged"


async def test_default_hooks_tag_prompt_with_git_branch(monkeypatch):
    monkeypatch.setattr("agent.app._git_branch", lambda cwd: "feature/x")
    hooks = _build_default_hooks(".")
    out = await _apply_prompt_submit(hooks, "hello", Console())
    assert "feature/x" in out
