"""Auto-retry: a turn that ends in a transient error is re-streamed per the policy."""

from __future__ import annotations

from typing import AsyncIterator

from agent.wire import StreamEvent

from agent.loop import run_agent
from agent.retry import RetryPolicy
from agent.types import AgentEnd, AgentRetry, user_message
from fakes import error_turn, text_turn


def test_delay_for_is_exponential_and_capped():
    policy = RetryPolicy(base_delay=1.0, backoff=2.0, max_delay=5.0)
    assert policy.delay_for(1) == 1.0
    assert policy.delay_for(2) == 2.0
    assert policy.delay_for(3) == 4.0
    assert policy.delay_for(4) == 5.0  # capped


class _ScriptedModel:
    """Replays scripted turns; records how many streams it served."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.streams = 0

    async def stream(self, *, system_prompt=None, messages, tools=None) -> AsyncIterator[StreamEvent]:
        self.streams += 1
        for event in self._turns.pop(0):
            yield event


async def _collect(model, history, **kwargs):
    return [e async for e in run_agent(model, [], history, **kwargs)]


async def test_retry_recovers_after_transient_error(monkeypatch):
    # First stream errors, second succeeds → the run completes.
    model = _ScriptedModel([error_turn("overloaded"), text_turn("recovered")])
    slept: list[float] = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr("agent.loop.asyncio.sleep", fake_sleep)

    history = [user_message("hi")]
    events = await _collect(model, history, retry=RetryPolicy(max_retries=2, base_delay=0.5))

    retries = [e for e in events if isinstance(e, AgentRetry)]
    assert len(retries) == 1
    assert retries[0].attempt == 1 and retries[0].error == "overloaded"
    assert slept == [0.5]
    assert model.streams == 2
    assert isinstance(events[-1], AgentEnd) and events[-1].reason == "completed"


async def test_retry_gives_up_after_max(monkeypatch):
    model = _ScriptedModel([error_turn("boom"), error_turn("boom"), error_turn("boom")])

    async def fake_sleep(delay):
        pass

    monkeypatch.setattr("agent.loop.asyncio.sleep", fake_sleep)

    history = [user_message("hi")]
    events = await _collect(model, history, retry=RetryPolicy(max_retries=2, base_delay=0.0))

    retries = [e for e in events if isinstance(e, AgentRetry)]
    assert len(retries) == 2  # max_retries attempts, then give up
    assert model.streams == 3
    assert isinstance(events[-1], AgentEnd) and events[-1].reason == "error"


async def test_no_retry_policy_means_no_retries():
    model = _ScriptedModel([error_turn("boom")])
    history = [user_message("hi")]
    events = await _collect(model, history)  # retry=None
    assert not any(isinstance(e, AgentRetry) for e in events)
    assert model.streams == 1
    assert isinstance(events[-1], AgentEnd) and events[-1].reason == "error"
