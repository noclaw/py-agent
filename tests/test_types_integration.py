"""Opt-in live test: the message types survive a real tool round-trip.

This is the key validation for the loop (Phase 5): a streamed assistant message replayed
verbatim, plus a tool-result message, must produce a correct continuation.

Run with:  PI_LIVE_LLM=1 pytest -m integration
"""

from __future__ import annotations

import os
import shutil

import pytest

from coding_agent.types import to_llm_messages, tool_result_message, user_message
from pi_py_sdk import PiModelClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("pi") is None, reason="`pi` not on PATH"),
    pytest.mark.skipif(shutil.which("node") is None, reason="`node` not on PATH"),
    pytest.mark.skipif(os.environ.get("PI_LIVE_LLM") != "1", reason="set PI_LIVE_LLM=1"),
]

_MODEL = os.environ.get("PI_LIVE_MODEL", "claude-haiku-4-5")
_PROVIDER = os.environ.get("PI_LIVE_PROVIDER", "anthropic")

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
    out = []
    for block in message.content:
        btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if btype == kind:
            out.append(block)
    return out


@pytest.mark.asyncio
async def test_tool_round_trip():
    history = [user_message("What is 17 * 23? Use the calculator tool, then state the number.")]
    async with PiModelClient() as client:
        first = await client.complete(
            provider=_PROVIDER, model=_MODEL, messages=to_llm_messages(history),
            tools=[_CALC], maxTokens=512,
        )
        history.append(first)
        calls = _blocks(first, "toolCall")
        assert first.stopReason == "toolUse"
        assert calls and calls[0]["name"] == "calculator"

        for call in calls:
            product = call["arguments"]["a"] * call["arguments"]["b"]
            history.append(tool_result_message(call["id"], call["name"], str(product)))

        second = await client.complete(
            provider=_PROVIDER, model=_MODEL, messages=to_llm_messages(history),
            tools=[_CALC], maxTokens=512,
        )
        text = "".join(b.get("text", "") for b in _blocks(second, "text"))
        assert "391" in text
