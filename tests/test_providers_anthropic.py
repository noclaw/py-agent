"""The Anthropic provider: message conversion, SSE parsing, thinking/signature, tool use."""

from __future__ import annotations

import httpx
import pytest

from agent.providers.anthropic import AnthropicProvider, to_anthropic_messages


# --- conversion -------------------------------------------------------------


def test_to_anthropic_messages_and_coalesce():
    wire = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "hmm", "signature": "SIG"},
            {"type": "text", "text": "calling"},
            {"type": "toolCall", "id": "c1", "name": "calc", "arguments": {"a": 2}},
        ]},
        {"role": "toolResult", "toolCallId": "c1", "toolName": "calc", "content": [{"type": "text", "text": "4"}], "isError": False},
        {"role": "toolResult", "toolCallId": "c2", "toolName": "calc", "content": [{"type": "text", "text": "9"}]},
    ]
    out = to_anthropic_messages(wire)
    assert out[0] == {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    asst = out[1]["content"]
    assert asst[0] == {"type": "thinking", "thinking": "hmm", "signature": "SIG"}  # signature preserved
    assert asst[1] == {"type": "text", "text": "calling"}
    assert asst[2] == {"type": "tool_use", "id": "c1", "name": "calc", "input": {"a": 2}}
    # The two consecutive tool results coalesce into one user turn.
    assert out[2]["role"] == "user" and len(out[2]["content"]) == 2
    assert out[2]["content"][0]["type"] == "tool_result" and out[2]["content"][0]["tool_use_id"] == "c1"


# --- streaming --------------------------------------------------------------


def _sse(*events: str) -> bytes:
    return "".join(f"data: {e}\n\n" for e in events).encode()


def _provider(body: bytes, status: int = 200) -> AnthropicProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})
    return AnthropicProvider(api_key="k", transport=httpx.MockTransport(handler))


async def _run(provider, *, reasoning=None):
    return [ev async for ev in provider.stream(
        model="claude-opus-4-8", system_prompt="be brief",
        messages=[{"role": "user", "content": "hi"}], tools=None, reasoning=reasoning)]


@pytest.mark.asyncio
async def test_stream_text_and_usage():
    events = await _run(_provider(_sse(
        '{"type":"message_start","message":{"usage":{"input_tokens":10}}}',
        '{"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
        '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hel"}}',
        '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"lo"}}',
        '{"type":"content_block_stop","index":0}',
        '{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":5}}',
        '{"type":"message_stop"}',
    )))
    assert [e.delta for e in events if e.type == "text_delta"] == ["Hel", "lo"]
    done = events[-1]
    assert done.final_message.content[0] == {"type": "text", "text": "Hello"}
    assert done.final_message.stopReason == "stop"
    assert done.final_message.usage["totalTokens"] == 15  # input + output


@pytest.mark.asyncio
async def test_stream_thinking_signature_and_tool_use():
    events = await _run(_provider(_sse(
        '{"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}',
        '{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"let me"}}',
        '{"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"ABC"}}',
        '{"type":"content_block_stop","index":0}',
        '{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"t1","name":"calc"}}',
        '{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"a\\":"}}',
        '{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"2}"}}',
        '{"type":"content_block_stop","index":1}',
        '{"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":7}}',
        '{"type":"message_stop"}',
    ), ), reasoning="high")
    assert [e.delta for e in events if e.type == "thinking_delta"] == ["let me"]
    msg = events[-1].final_message
    assert msg.stopReason == "toolUse"
    # thinking block keeps its signature for the next turn to replay
    assert msg.content[0] == {"type": "thinking", "thinking": "let me", "signature": "ABC"}
    assert msg.content[1] == {"type": "toolCall", "id": "t1", "name": "calc", "arguments": {"a": 2}}


@pytest.mark.asyncio
async def test_http_error_becomes_error_event():
    events = await _run(_provider(b'{"error":{"message":"bad"}}', status=400))
    assert events[0].type == "error" and "400" in events[0].final_message.errorMessage


@pytest.mark.asyncio
async def test_stream_error_event():
    events = await _run(_provider(_sse('{"type":"error","error":{"message":"overloaded"}}')))
    assert events[-1].type == "error" and "overloaded" in events[-1].final_message.errorMessage


def test_reasoning_sets_thinking_and_effort():
    p = AnthropicProvider(api_key="k")
    body = p._build_body("claude-opus-4-8", None, [{"role": "user", "content": "hi"}], None, "xhigh", {})
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "xhigh"}
    assert body["max_tokens"] == 16384  # default applied


@pytest.mark.asyncio
async def test_list_models():
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "claude-opus-4-8"}, {"id": "claude-haiku-4-5"}]})
    p = AnthropicProvider(api_key="k", transport=httpx.MockTransport(handler))
    models = await p.list_models()
    assert {m["id"] for m in models} == {"claude-opus-4-8", "claude-haiku-4-5"}
    assert all(m["provider"] == "anthropic" for m in models)
