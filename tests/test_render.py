"""Phase 7: the renderer turns events into terminal output."""

from __future__ import annotations

import io

from rich.console import Console

from coding_agent.render import Renderer
from coding_agent.types import (
    AgentEnd,
    AgentStart,
    AssistantDelta,
    AssistantDone,
    ToolEnd,
    ToolResult,
    ToolStart,
)
from pi_py_sdk import AssistantMessage, StreamEvent


def _renderer():
    buffer = io.StringIO()
    # force_terminal=False keeps ANSI styling out so we can assert on plain text.
    console = Console(file=buffer, force_terminal=False, width=200)
    return Renderer(console), buffer


def test_streams_text_then_done():
    renderer, buf = _renderer()
    for event in [
        AgentStart(),
        AssistantDelta(StreamEvent(type="text_delta", delta="Hello ")),
        AssistantDelta(StreamEvent(type="text_delta", delta="world")),
        AssistantDone(AssistantMessage(role="assistant", content=[], usage={"totalTokens": 12})),
        AgentEnd("completed"),
    ]:
        renderer.handle(event)
    out = buf.getvalue()
    assert "Hello world" in out
    assert "done" in out
    assert "12 tokens" in out


def test_renders_tool_call_and_result():
    renderer, buf = _renderer()
    renderer.handle(ToolStart("c1", "bash", {"command": "ls"}))
    renderer.handle(ToolEnd("c1", "bash", ToolResult(content="file.txt\nother.txt")))
    out = buf.getvalue()
    assert "bash" in out
    assert "ls" in out
    assert "file.txt" in out  # first line of the result preview


def test_renders_tool_error():
    renderer, buf = _renderer()
    renderer.handle(ToolEnd("c1", "read", ToolResult(content="File not found", is_error=True)))
    assert "File not found" in buf.getvalue()


def test_thinking_can_be_hidden():
    buffer = io.StringIO()
    renderer = Renderer(Console(file=buffer, force_terminal=False, width=200), show_thinking=False)
    renderer.handle(AssistantDelta(StreamEvent(type="thinking_delta", delta="secret reasoning")))
    assert "secret reasoning" not in buffer.getvalue()
