"""The Model adapter's routing: native (OpenAI-compatible) vs the transitional pi backend."""

from __future__ import annotations

import httpx
import pytest

from agent.model import Model


class _RecordingPi:
    """Stands in for PiModelClient: records stream kwargs, tracks lazy start/stop."""

    def __init__(self):
        self.last = None
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def stream(self, **kwargs):
        self.last = kwargs
        return
        yield  # async generator

    async def list_models(self, provider=None):
        return [{"provider": "anthropic", "id": "claude-sonnet-4-6"}]


def _sse(*chunks: str) -> bytes:
    return ("".join(f"data: {c}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _mock_transport(body: bytes, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


async def _drain(model):
    return [ev async for ev in model.stream(messages=[{"role": "user", "content": "hi"}])]


@pytest.mark.asyncio
async def test_anthropic_routes_to_pi_backend():
    pi = _RecordingPi()
    model = Model(pi, provider="anthropic", model="claude-sonnet-4-6")
    await _drain(model)
    assert pi.started is True  # lazily started for the pi path
    assert pi.last["provider"] == "anthropic"
    assert pi.last["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_openai_routes_native_not_pi():
    pi = _RecordingPi()
    transport = _mock_transport(_sse(
        '{"choices":[{"delta":{"content":"hi"}}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":4}}',
    ))
    model = Model(pi, provider="openai", model="gpt-5.1", transport=transport)
    events = await _drain(model)
    assert pi.started is False and pi.last is None  # pi never touched → no Node
    assert events[-1].type == "done"
    assert events[-1].final_message.content[0]["text"] == "hi"
    assert events[-1].final_message.usage["totalTokens"] == 4


@pytest.mark.asyncio
async def test_custom_local_spec_routes_native():
    pi = _RecordingPi()
    spec = {"id": "qwen3", "provider": "local", "api": "openai-completions", "baseUrl": "http://x/v1"}
    transport = _mock_transport(_sse('{"choices":[{"delta":{"content":"yo"}},{"finish_reason":"stop"}]}'))
    model = Model(pi, provider="local", model="qwen3", spec=spec, transport=transport)
    events = await _drain(model)
    assert pi.last is None  # native, not pi
    assert events[-1].final_message.content[0]["text"] == "yo"


@pytest.mark.asyncio
async def test_set_model_reroutes():
    pi = _RecordingPi()
    transport = _mock_transport(_sse('{"choices":[{"delta":{"content":"x"},"finish_reason":"stop"}]}'))
    model = Model(pi, provider="openai", model="gpt-5.1", transport=transport)
    await _drain(model)                       # native
    assert pi.last is None
    model.set_model("claude-opus-4-8", "anthropic")
    await _drain(model)                        # now pi
    assert pi.last is not None and pi.last["model"] == "claude-opus-4-8"
