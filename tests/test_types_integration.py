"""Opt-in live test: the message types survive a real tool round-trip (native provider).

A streamed assistant message replayed verbatim, plus a tool-result message, must produce a
correct continuation.

Run with:  PYA_LIVE_LLM=1 pytest -m integration
"""

from __future__ import annotations

import os

import pytest

from agent.model import open_model
from agent.types import to_llm_messages, tool_result_message, user_message

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("PYA_LIVE_LLM") != "1", reason="set PYA_LIVE_LLM=1"),
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"),
]

_MODEL = os.environ.get("PYA_LIVE_MODEL", "claude-haiku-4-5")
_PROVIDER = os.environ.get("PYA_LIVE_PROVIDER", "anthropic")

_CALC = {
    "name": "calculator",
    "description": "Multiply two integers",
    "parameters": {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    },
}


def _blocks(message, kind):
    return [b for b in message.content if isinstance(b, dict) and b.get("type") == kind]


async def _turn(model, history):
    final = None
    async for ev in model.stream(messages=to_llm_messages(history), tools=[_CALC]):
        if ev.is_terminal:
            final = ev.final_message
    return final


@pytest.mark.asyncio
async def test_tool_round_trip():
    history = [user_message("What is 17 * 23? Use the calculator tool, then state the number.")]
    async with open_model(provider=_PROVIDER, model=_MODEL) as model:
        first = await _turn(model, history)
        history.append(first)
        calls = _blocks(first, "toolCall")
        assert first.stopReason == "toolUse"
        assert calls and calls[0]["name"] == "calculator"

        for call in calls:
            product = call["arguments"]["a"] * call["arguments"]["b"]
            history.append(tool_result_message(call["id"], call["name"], str(product)))

        second = await _turn(model, history)
        text = "".join(b.get("text", "") for b in _blocks(second, "text"))
        assert "391" in text
