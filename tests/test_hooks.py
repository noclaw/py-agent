"""The hooks registry: registration, matchers, sync/async, decisions."""

from __future__ import annotations

from agent.hooks import Hooks, HookResult, PostToolUse, PreToolUse, UserPromptSubmit
from agent.types import ToolResult


async def test_pre_tool_use_deny_decision():
    hooks = Hooks()

    @hooks.pre_tool_use(matcher="bash")
    def block_rm(event: PreToolUse):
        if "rm -rf" in event.tool_input.get("command", ""):
            return HookResult(decision="deny", reason="no rm -rf")

    denied = await hooks.run(PreToolUse("bash", {"command": "rm -rf /"}, "c1"))
    assert denied and denied[0].decision == "deny"

    allowed = await hooks.run(PreToolUse("bash", {"command": "ls"}, "c2"))
    assert allowed == []  # hook returned None → no result


async def test_matcher_filters_by_tool_name():
    hooks = Hooks()
    seen: list[str] = []

    @hooks.pre_tool_use(matcher="write|edit")
    def record(event: PreToolUse):
        seen.append(event.tool_name)

    await hooks.run(PreToolUse("read", {}, "c"))
    await hooks.run(PreToolUse("write", {}, "c"))
    await hooks.run(PreToolUse("edit", {}, "c"))
    assert seen == ["write", "edit"]


async def test_async_post_tool_use_adds_context():
    hooks = Hooks()

    @hooks.post_tool_use()
    async def lint(event: PostToolUse):
        return HookResult(additional_context="linted")

    results = await hooks.run(PostToolUse("write", {}, "c", ToolResult(content="ok")))
    assert results[0].additional_context == "linted"


async def test_user_prompt_submit():
    hooks = Hooks()

    @hooks.user_prompt_submit()
    def add_context(event: UserPromptSubmit):
        return HookResult(additional_context=f"(len={len(event.prompt)})")

    results = await hooks.run(UserPromptSubmit("hello"))
    assert results[0].additional_context == "(len=5)"


async def test_multiple_hooks_collected_in_order():
    hooks = Hooks()
    hooks.add("PreToolUse", lambda e: HookResult(reason="a"))
    hooks.add("PreToolUse", lambda e: HookResult(reason="b"))
    results = await hooks.run(PreToolUse("read", {}, "c"))
    assert [r.reason for r in results] == ["a", "b"]
