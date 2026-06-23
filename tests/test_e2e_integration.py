"""Opt-in live end-to-end test: the real model + real tools complete a coding task.

Run with:  PI_LIVE_LLM=1 pytest -m integration
"""

from __future__ import annotations

import os
import shutil

import pytest

from coding_agent.loop import run_agent
from coding_agent.model import open_model
from coding_agent.tools import coding_tools
from coding_agent.types import AgentEnd, user_message

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("pi") is None, reason="`pi` not on PATH"),
    pytest.mark.skipif(shutil.which("node") is None, reason="`node` not on PATH"),
    pytest.mark.skipif(os.environ.get("PI_LIVE_LLM") != "1", reason="set PI_LIVE_LLM=1"),
]

_MODEL = os.environ.get("PI_LIVE_MODEL", "claude-haiku-4-5")
_PROVIDER = os.environ.get("PI_LIVE_PROVIDER", "anthropic")


@pytest.mark.asyncio
async def test_agent_writes_a_file(tmp_path):
    history = [
        user_message(
            "Create a file named answer.txt whose entire contents are exactly the result "
            "of multiplying 6 by 7 (just the number, no other text). Then stop."
        )
    ]
    reason = None
    async with open_model(provider=_PROVIDER, model=_MODEL, maxTokens=2000) as model:
        async for event in run_agent(
            model, coding_tools(tmp_path), history, system_prompt="You are a coding assistant."
        ):
            if isinstance(event, AgentEnd):
                reason = event.reason

    assert reason == "completed"
    answer = tmp_path / "answer.txt"
    assert answer.exists(), "agent did not create answer.txt"
    assert "42" in answer.read_text()
