"""The OpenAI-compatible provider: request building, SSE parsing, tool calls, errors."""

from __future__ import annotations

import json

import httpx
import pytest

from agent.providers.openai_compat import (
    OpenAICompatProvider,
    to_openai_messages,
    to_openai_tools,
)


# --- pure conversion (no network) ------------------------------------------


def test_to_openai_messages_roles():
    wire = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "calling"},
            {"type": "toolCall", "id": "c1", "name": "read", "arguments": {"path": "x"}},
        ]},
        {"role": "toolResult", "toolCallId": "c1", "toolName": "read", "content": [{"type": "text", "text": "FILE"}]},
    ]
    out = to_openai_messages("be brief", wire)
    assert out[0] == {"role": "system", "content": "be brief"}
    assert out[1] == {"role": "user", "content": "hello"}
    asst = out[2]
    assert asst["role"] == "assistant" and asst["content"] == "calling"
    assert asst["tool_calls"][0]["id"] == "c1"
    assert json.loads(asst["tool_calls"][0]["function"]["arguments"]) == {"path": "x"}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "FILE"}


def test_to_openai_tools():
    tools = [{"name": "read", "description": "Read a file", "parameters": {"type": "object"}}]
    out = to_openai_tools(tools)
    assert out[0]["type"] == "function" and out[0]["function"]["name"] == "read"
    assert to_openai_tools(None) is None


# --- streaming (httpx MockTransport feeds canned SSE) -----------------------


def _sse(*chunks: str) -> bytes:
    return ("".join(f"data: {c}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _provider(body: bytes, status: int = 200) -> OpenAICompatProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})
    return OpenAICompatProvider(base_url="http://x/v1", api_key="k", transport=httpx.MockTransport(handler))


async def _run(provider):
    return [ev async for ev in provider.stream(
        model="m", system_prompt=None, messages=[{"role": "user", "content": "hi"}], tools=None)]


@pytest.mark.asyncio
async def test_stream_text_and_usage():
    p = _provider(_sse(
        '{"choices":[{"delta":{"content":"Hel"}}]}',
        '{"choices":[{"delta":{"content":"lo"}}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}',
    ))
    events = await _run(p)
    deltas = [e.delta for e in events if e.type == "text_delta"]
    assert deltas == ["Hel", "lo"]
    done = events[-1]
    assert done.type == "done" and done.final_message.stopReason == "stop"
    assert done.final_message.content[0]["text"] == "Hello"
    assert done.final_message.usage["totalTokens"] == 7


@pytest.mark.asyncio
async def test_stream_tool_call_assembled_across_chunks():
    p = _provider(_sse(
        '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"read","arguments":"{\\"pa"}}]}}]}',
        '{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"th\\":\\"a.txt\\"}"}}]}}]}',
        '{"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
    ))
    events = await _run(p)
    msg = events[-1].final_message
    assert msg.stopReason == "toolUse"
    call = msg.content[0]
    assert call["type"] == "toolCall" and call["id"] == "c1" and call["name"] == "read"
    assert call["arguments"] == {"path": "a.txt"}  # fragments reassembled + parsed


@pytest.mark.asyncio
async def test_http_error_becomes_error_event():
    p = _provider(b'{"error":"nope"}', status=500)
    events = await _run(p)
    assert len(events) == 1 and events[0].type == "error"
    assert events[0].final_message.stopReason == "error"
    assert "500" in events[0].final_message.errorMessage


@pytest.mark.asyncio
async def test_list_models():
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "gpt-5.1"}, {"id": "gpt-4o"}]})
    p = OpenAICompatProvider(base_url="http://x/v1", provider="openai", transport=httpx.MockTransport(handler))
    models = await p.list_models()
    assert {m["id"] for m in models} == {"gpt-5.1", "gpt-4o"}
    assert all(m["provider"] == "openai" for m in models)
