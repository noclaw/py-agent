"""Test doubles: a scripted fake model and helpers to build streamed turns.

The fake model is the most important fixture in the project — it lets the loop be tested
deterministically with no network. Each ``stream()`` call replays the next scripted turn.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from pi_py_sdk import AssistantMessage, StreamEvent


def text_turn(text: str) -> list[StreamEvent]:
    """A turn where the assistant just replies with text and stops."""
    message = AssistantMessage(
        role="assistant", content=[{"type": "text", "text": text}], stopReason="stop"
    )
    return [
        StreamEvent(type="text_delta", contentIndex=0, delta=text),
        StreamEvent(type="done", reason="stop", message=message),
    ]


def tool_turn(calls: list[tuple[str, str, dict[str, Any]]]) -> list[StreamEvent]:
    """A turn where the assistant makes one or more tool calls.

    ``calls`` is a list of ``(id, name, arguments)`` tuples.
    """
    from pi_py_sdk import ToolCall

    content = [{"type": "toolCall", "id": i, "name": n, "arguments": a} for i, n, a in calls]
    message = AssistantMessage(role="assistant", content=content, stopReason="toolUse")
    events: list[StreamEvent] = [
        StreamEvent(type="toolcall_end", contentIndex=k, toolCall=ToolCall(id=i, name=n, arguments=a))
        for k, (i, n, a) in enumerate(calls)
    ]
    events.append(StreamEvent(type="done", reason="toolUse", message=message))
    return events


def error_turn(message: str = "boom") -> list[StreamEvent]:
    """A turn that terminates with a model error event."""
    failed = AssistantMessage(
        role="assistant", content=[], stopReason="error", errorMessage=message
    )
    return [StreamEvent(type="error", reason="error", error=failed)]


class FakeModel:
    """Replays a fixed list of scripted turns, one per ``stream()`` call.

    Records each call's inputs on ``self.calls`` for assertions.
    """

    def __init__(self, turns: list[list[StreamEvent]]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self, *, system_prompt=None, messages, tools=None
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append({"system_prompt": system_prompt, "messages": messages, "tools": tools})
        if not self._turns:
            raise AssertionError("FakeModel ran out of scripted turns")
        for event in self._turns.pop(0):
            yield event


class LoopingToolModel:
    """Always asks for the same tool call — to exercise the max-turns safety cap."""

    def __init__(self, name: str = "noop") -> None:
        self._name = name
        self.calls = 0

    async def stream(self, *, system_prompt=None, messages, tools=None) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        for event in tool_turn([(f"c{self.calls}", self._name, {})]):
            yield event
