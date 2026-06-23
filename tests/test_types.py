"""Phase 2: message conversion, Tool schema, and event types."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent.types import (
    AssistantDelta,
    Tool,
    ToolResult,
    UserMessage,
    to_llm_messages,
    tool_result_message,
    tools_to_wire,
    user_message,
)
from pi_py_sdk import AssistantMessage, StreamEvent


def test_user_message_to_wire():
    msg = UserMessage(content="hello", timestamp=123)
    assert msg.to_wire() == {"role": "user", "content": "hello", "timestamp": 123}


def test_tool_result_to_wire_uses_camelcase_and_block_content():
    msg = tool_result_message("call_1", "read", "file contents", is_error=False)
    wire = msg.to_wire()
    assert wire["role"] == "toolResult"
    assert wire["toolCallId"] == "call_1"
    assert wire["toolName"] == "read"
    assert wire["isError"] is False
    assert wire["content"] == [{"type": "text", "text": "file contents"}]


def test_to_llm_messages_round_trips_a_tool_turn():
    # user -> assistant (with a tool call) -> toolResult, as the loop would accumulate it.
    assistant = AssistantMessage(
        role="assistant",
        content=[
            {"type": "text", "text": "let me read it"},
            {"type": "toolCall", "id": "call_1", "name": "read", "arguments": {"path": "a.py"}},
        ],
        provider="anthropic",
        model="claude-sonnet-4-6",
        stopReason="toolUse",
    )
    history = [
        user_message("read a.py"),
        assistant,
        tool_result_message("call_1", "read", "print('hi')"),
    ]
    wire = to_llm_messages(history)

    assert [m["role"] for m in wire] == ["user", "assistant", "toolResult"]
    # The assistant message is replayed verbatim, preserving its tool-call block.
    assert wire[1]["content"][1]["name"] == "read"
    assert wire[1]["stopReason"] == "toolUse"
    # No null fields leak into the replayed message.
    assert "errorMessage" not in wire[1]


def test_assistant_dict_passthrough():
    history = [{"role": "assistant", "content": [{"type": "text", "text": "hi"}]}]
    assert to_llm_messages(history) == history  # type: ignore[arg-type]


class _Args(BaseModel):
    path: str = Field(description="File path")
    limit: int = 100


class _DummyTool(Tool):
    name = "dummy"
    description = "A dummy tool"
    parameters = _Args

    async def execute(self, args, *, on_update=None):  # noqa: ANN001
        return ToolResult(content=f"got {args.path}")


def test_tool_json_schema_and_wire():
    schema = _DummyTool.json_schema()
    assert schema["type"] == "object"
    assert "path" in schema["properties"]
    assert "path" in schema["required"]
    assert "limit" not in schema["required"]  # has a default
    assert "title" not in schema  # stripped

    wire = _DummyTool.to_wire()
    assert wire["name"] == "dummy"
    assert wire["description"] == "A dummy tool"
    assert wire["parameters"] == schema

    assert tools_to_wire([_DummyTool]) == [wire]


async def test_tool_execute_validates_and_runs():
    args = _DummyTool.parameters.model_validate({"path": "x.py"})
    result = await _DummyTool().execute(args)
    assert isinstance(result, ToolResult)
    assert result.content == "got x.py"
    assert result.is_error is False


def test_event_wraps_stream_event():
    ev = AssistantDelta(event=StreamEvent(type="text_delta", delta="hi"))
    assert ev.event.delta == "hi"
