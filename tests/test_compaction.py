"""Compaction: summarize old history when the estimate nears the context window."""

from __future__ import annotations

from pi_py_sdk import AssistantMessage

from agent.compaction import CompactionConfig, Compactor, estimate_tokens
from agent.types import (
    CompactionEnd,
    CompactionStart,
    ToolResultMessage,
    UserMessage,
    user_message,
)
from fakes import FakeModel, text_turn


def _assistant(text: str, *, total_tokens: int | None = None) -> AssistantMessage:
    usage = {"totalTokens": total_tokens} if total_tokens is not None else None
    return AssistantMessage(
        role="assistant", content=[{"type": "text", "text": text}], stopReason="stop", usage=usage
    )


def test_estimate_prefers_reported_usage():
    history = [user_message("hi"), _assistant("reply", total_tokens=1234)]
    assert estimate_tokens(history) == 1234


def test_estimate_falls_back_to_char_count():
    history = [user_message("x" * 400)]
    # ~4 chars per token over the serialized message.
    assert estimate_tokens(history) > 50


def _events() -> list:
    return []


async def test_no_compaction_below_threshold():
    model = FakeModel([])  # never streamed
    compactor = Compactor(model, CompactionConfig(max_tokens=1000, threshold=0.8, keep_recent=2))
    history = [user_message("hi"), _assistant("reply", total_tokens=100)]
    result = await compactor.transform(history, _events().append)
    assert result is None  # 100 << 800


async def test_compaction_summarizes_head_keeps_tail():
    model = FakeModel([text_turn("CONDENSED SUMMARY")])
    compactor = Compactor(model, CompactionConfig(max_tokens=100, threshold=0.8, keep_recent=2))
    history = [
        user_message("first goal"),
        _assistant("did a thing"),
        user_message("second ask"),
        _assistant("did more"),
        user_message("third ask"),
        _assistant("over the limit", total_tokens=100),  # triggers compaction
    ]
    events: list = []
    result = await compactor.transform(history, events.append)

    assert result is not None
    # New history: one summary user-message + the kept tail (keep_recent=2).
    assert isinstance(result[0], UserMessage)
    assert "CONDENSED SUMMARY" in result[0].content
    assert len(result) == 1 + 2
    assert result[-2:] == history[-2:]

    # Emitted start/end events bracket the work.
    assert any(isinstance(e, CompactionStart) for e in events)
    end = [e for e in events if isinstance(e, CompactionEnd)][0]
    assert end.before_messages == 6 and end.after_messages == 3


async def test_split_does_not_orphan_tool_results():
    model = FakeModel([text_turn("S")])
    compactor = Compactor(model, CompactionConfig(max_tokens=100, threshold=0.8, keep_recent=2))
    # keep_recent=2 would land the tail boundary on a tool-result; it must walk back.
    history = [
        user_message("go"),
        _assistant("call a tool"),
        ToolResultMessage(tool_call_id="c1", tool_name="read", content="data"),
        ToolResultMessage(tool_call_id="c2", tool_name="read", content="more", timestamp=1),
        _assistant("final", total_tokens=100),
    ]
    result = await compactor.transform(history, [].append)
    assert result is not None
    # The tail must not begin with a tool-result (it would be orphaned from its call).
    assert not isinstance(result[1], ToolResultMessage)
