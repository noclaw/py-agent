"""Phase 5: the agent loop, driven by the scripted fake model (no network)."""

from __future__ import annotations

from pydantic import BaseModel

from agent.hooks import Hooks, HookResult
from agent.loop import run_agent
from agent.permissions import PermissionMode, Permissions
from agent.types import (
    AgentEnd,
    AgentStart,
    AssistantDone,
    Tool,
    ToolEnd,
    ToolOutput,
    ToolResult,
    ToolResultMessage,
    ToolStart,
    user_message,
)
from fakes import FakeModel, LoopingToolModel, error_turn, text_turn, tool_turn

_BYPASS = Permissions(mode=PermissionMode.BYPASS)


class EchoArgs(BaseModel):
    text: str


class EchoTool(Tool):
    name = "echo"
    description = "Echo the given text back."
    parameters = EchoArgs

    async def execute(self, args: EchoArgs, *, on_update=None) -> ToolResult:
        if on_update is not None:
            on_update("working...")
        return ToolResult(content=args.text)


class SeqEchoTool(EchoTool):
    name = "seq_echo"
    execution_mode = "sequential"


async def _collect(model, tools, history, **kwargs):
    return [event async for event in run_agent(model, tools, history, **kwargs)]


async def test_text_only_completion():
    history = [user_message("hi")]
    events = await _collect(FakeModel([text_turn("Hello!")]), [], history)

    assert isinstance(events[0], AgentStart)
    assert isinstance(events[-1], AgentEnd) and events[-1].reason == "completed"
    assert any(isinstance(e, AssistantDone) for e in events)
    # History gained the assistant reply.
    assert len(history) == 2
    assert history[-1].stopReason == "stop"


async def test_tool_call_then_completion():
    history = [user_message("say hi")]
    model = FakeModel([tool_turn([("c1", "echo", {"text": "hi there"})]), text_turn("done")])

    events = await _collect(model, [EchoTool()], history)

    tool_ends = [e for e in events if isinstance(e, ToolEnd)]
    assert len(tool_ends) == 1
    assert tool_ends[0].result.content == "hi there"
    assert tool_ends[0].result.is_error is False

    # History: user, assistant(toolUse), toolResult, assistant(text)
    roles = [getattr(m, "role", None) for m in history]
    assert roles == ["user", "assistant", "toolResult", "assistant"]

    # The second model call saw the tool result.
    assert len(model.calls) == 2
    assert any(m.get("role") == "toolResult" for m in model.calls[1]["messages"])


async def test_tool_output_is_streamed():
    history = [user_message("go")]
    model = FakeModel([tool_turn([("c1", "echo", {"text": "x"})]), text_turn("ok")])
    events = await _collect(model, [EchoTool()], history)
    outputs = [e for e in events if isinstance(e, ToolOutput)]
    assert outputs and outputs[0].chunk == "working..."
    # ToolStart precedes ToolEnd for the call.
    order = [type(e).__name__ for e in events if isinstance(e, (ToolStart, ToolEnd))]
    assert order == ["ToolStart", "ToolEnd"]


async def test_unknown_tool_is_reported_not_raised():
    history = [user_message("x")]
    model = FakeModel([tool_turn([("c1", "missing", {})]), text_turn("ok")])
    events = await _collect(model, [EchoTool()], history)
    end = [e for e in events if isinstance(e, ToolEnd)][0]
    assert end.result.is_error and "Unknown tool" in end.result.content


async def test_invalid_arguments_are_reported():
    history = [user_message("x")]
    model = FakeModel([tool_turn([("c1", "echo", {})]), text_turn("ok")])  # missing 'text'
    events = await _collect(model, [EchoTool()], history)
    end = [e for e in events if isinstance(e, ToolEnd)][0]
    assert end.result.is_error and "Invalid arguments" in end.result.content


async def test_parallel_results_preserve_call_order():
    history = [user_message("x")]
    model = FakeModel(
        [
            tool_turn([("c1", "echo", {"text": "A"}), ("c2", "echo", {"text": "B"})]),
            text_turn("ok"),
        ]
    )
    await _collect(model, [EchoTool()], history)
    results = [m for m in history if isinstance(m, ToolResultMessage)]
    assert [r.tool_call_id for r in results] == ["c1", "c2"]
    assert [r.content for r in results] == ["A", "B"]


async def test_sequential_tool_runs():
    history = [user_message("x")]
    model = FakeModel([tool_turn([("c1", "seq_echo", {"text": "A"})]), text_turn("ok")])
    await _collect(model, [SeqEchoTool()], history)
    results = [m for m in history if isinstance(m, ToolResultMessage)]
    assert results[0].content == "A"


async def test_error_terminal_ends_run():
    history = [user_message("x")]
    events = await _collect(FakeModel([error_turn("rate limited")]), [], history)
    end = events[-1]
    assert isinstance(end, AgentEnd) and end.reason == "error"
    # The failed assistant message is still recorded.
    assert history[-1].errorMessage == "rate limited"


async def test_max_turns_cap():
    history = [user_message("x")]
    model = LoopingToolModel("echo")
    events = await _collect(model, [EchoTool()], history, max_turns=3)
    assert isinstance(events[-1], AgentEnd) and events[-1].reason == "error"
    assert model.calls == 3


# --- gating: permissions + hooks ------------------------------------------


def _one_echo_then_done():
    return FakeModel([tool_turn([("c1", "echo", {"text": "hi"})]), text_turn("ok")])


async def test_permission_deny_blocks_tool():
    history = [user_message("x")]
    events = await _collect(
        _one_echo_then_done(), [EchoTool()], history, permissions=Permissions(deny=["echo"])
    )
    end = [e for e in events if isinstance(e, ToolEnd)][0]
    assert end.result.is_error and "denied" in end.result.content.lower()


async def test_permission_ask_requires_approver():
    history = [user_message("x")]
    # echo is not a read-only tool, so default mode → ask; no approver → blocked.
    events = await _collect(_one_echo_then_done(), [EchoTool()], history, permissions=Permissions())
    end = [e for e in events if isinstance(e, ToolEnd)][0]
    assert end.result.is_error and "approval" in end.result.content.lower()


async def test_permission_ask_approver_allows():
    history = [user_message("x")]

    async def approver(name, args, reason):
        return "once"

    events = await _collect(
        _one_echo_then_done(), [EchoTool()], history, permissions=Permissions(), approver=approver
    )
    end = [e for e in events if isinstance(e, ToolEnd)][0]
    assert not end.result.is_error and end.result.content == "hi"


async def test_permission_always_remembers_for_later_calls():
    history = [user_message("x")]
    calls = []

    async def approver(name, args, reason):
        calls.append(name)
        return "always"

    model = FakeModel(
        [
            tool_turn([("c1", "echo", {"text": "a"})]),
            tool_turn([("c2", "echo", {"text": "b"})]),
            text_turn("ok"),
        ]
    )
    await _collect(model, [EchoTool()], history, permissions=Permissions(), approver=approver)
    assert calls == ["echo"]  # approver asked once; second call auto-allowed by the rule
    results = [m for m in history if isinstance(m, ToolResultMessage)]
    assert [r.content for r in results] == ["a", "b"]


async def test_hook_deny_blocks_even_in_bypass():
    history = [user_message("x")]
    hooks = Hooks()

    @hooks.pre_tool_use(matcher="echo")
    def deny(event):
        return HookResult(decision="deny", reason="nope")

    events = await _collect(
        _one_echo_then_done(), [EchoTool()], history, hooks=hooks, permissions=_BYPASS
    )
    end = [e for e in events if isinstance(e, ToolEnd)][0]
    assert end.result.is_error and "hook" in end.result.content.lower()


async def test_post_tool_use_appends_context():
    history = [user_message("x")]
    hooks = Hooks()

    @hooks.post_tool_use()
    def tag(event):
        return HookResult(additional_context="[checked]")

    events = await _collect(
        _one_echo_then_done(), [EchoTool()], history, hooks=hooks, permissions=_BYPASS
    )
    end = [e for e in events if isinstance(e, ToolEnd)][0]
    assert "[checked]" in end.result.content
