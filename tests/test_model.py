"""The Model adapter's routing: OpenAI-compatible vs Anthropic, by the model's api."""

from __future__ import annotations

import httpx
import pytest

from agent.model import Model
from agent.providers import ProviderError


def _mock_transport(body: bytes, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


def _openai_sse(*chunks: str) -> bytes:
    return ("".join(f"data: {c}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _anthropic_sse(*events: str) -> bytes:
    return "".join(f"data: {e}\n\n" for e in events).encode()


async def _drain(model):
    return [ev async for ev in model.stream(messages=[{"role": "user", "content": "hi"}])]


@pytest.mark.asyncio
async def test_openai_provider_routing():
    transport = _mock_transport(_openai_sse(
        '{"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}],"usage":{"total_tokens":4}}',
    ))
    model = Model(provider="openai", model="gpt-5.1", transport=transport)
    events = await _drain(model)
    assert events[-1].type == "done"
    assert events[-1].final_message.content[0]["text"] == "hi"


@pytest.mark.asyncio
async def test_anthropic_provider_routing():
    transport = _mock_transport(_anthropic_sse(
        '{"type":"message_start","message":{"usage":{"input_tokens":3}}}',
        '{"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
        '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hello"}}',
        '{"type":"content_block_stop","index":0}',
        '{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}',
        '{"type":"message_stop"}',
    ))
    model = Model(provider="anthropic", model="claude-opus-4-8", transport=transport)
    events = await _drain(model)
    assert [e.delta for e in events if e.type == "text_delta"] == ["hello"]
    done = events[-1]
    assert done.type == "done" and done.final_message.stopReason == "stop"
    assert done.final_message.content[0]["text"] == "hello"
    assert done.final_message.usage["totalTokens"] == 5


@pytest.mark.asyncio
async def test_custom_local_spec_routes_openai_compatible():
    spec = {"id": "qwen3", "provider": "local", "api": "openai-completions", "baseUrl": "http://x/v1"}
    transport = _mock_transport(_openai_sse('{"choices":[{"delta":{"content":"yo"},"finish_reason":"stop"}]}'))
    model = Model(provider="local", model="qwen3", spec=spec, transport=transport)
    events = await _drain(model)
    assert events[-1].final_message.content[0]["text"] == "yo"


@pytest.mark.asyncio
async def test_unknown_provider_raises():
    model = Model(provider="mystery", model="m")
    with pytest.raises(ProviderError):
        await _drain(model)


@pytest.mark.asyncio
async def test_set_model_reroutes():
    transport = _mock_transport(_openai_sse('{"choices":[{"delta":{"content":"x"},"finish_reason":"stop"}]}'))
    model = Model(provider="openai", model="gpt-5.1", transport=transport)
    assert model._route().api == "openai-completions"
    model.set_model("claude-opus-4-8", "anthropic")
    assert model._route().api == "anthropic-messages"
