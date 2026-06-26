"""OpenAI-compatible provider — ``POST /chat/completions`` over httpx.

Covers OpenAI and the many servers that speak the same protocol: Ollama, LM Studio, vLLM,
llama.cpp, Together, Groq, OpenRouter, … This is Providers Phase 1 (see ``PROVIDERS.md``).

It converts py-agent's wire messages (pi-ai shape) to OpenAI Chat Completions, streams the
SSE response, assembles tool-call argument fragments, and emits the same ``StreamEvent`` /
``AssistantMessage`` objects the loop already consumes — so nothing downstream changes.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from ..wire import AssistantMessage, StreamEvent
from .http import DEFAULT_TIMEOUT, iter_sse

__all__ = ["OpenAICompatProvider"]

#: OpenAI finish_reason -> our stopReason vocabulary (what the loop/retry expect).
_STOP = {"stop": "stop", "length": "length", "tool_calls": "toolUse", "function_call": "toolUse"}


def _text_of(content: Any) -> str:
    """Plain text from a wire content value (a string, or a list of text blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def to_openai_messages(system_prompt: str | None, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert pi-ai wire messages to OpenAI Chat Completions messages."""
    out: list[dict[str, Any]] = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})
    for m in messages:
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "content": _text_of(m.get("content"))})
        elif role == "toolResult":
            out.append({
                "role": "tool",
                "tool_call_id": m.get("toolCallId", ""),
                "content": _text_of(m.get("content")),
            })
        elif role == "assistant":
            blocks = m.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            tool_calls = [
                {
                    "id": b.get("id", ""),
                    "type": "function",
                    "function": {"name": b.get("name", ""), "arguments": json.dumps(b.get("arguments") or {})},
                }
                for b in blocks
                if b.get("type") == "toolCall"
            ]
            msg: dict[str, Any] = {"role": "assistant", "content": text or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
    return out


def to_openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""), "parameters": t.get("parameters", {})}}
        for t in tools
    ]


def _error_event(message: str) -> StreamEvent:
    failed = AssistantMessage(role="assistant", content=[], stopReason="error", errorMessage=message)
    return StreamEvent(type="error", reason="error", error=failed)


class OpenAICompatProvider:
    """Streams from an OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        provider: str = "openai",
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._provider = provider
        self._transport = transport
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _build_body(
        self, model: str, system_prompt: str | None, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None, reasoning: str | None, options: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": to_openai_messages(system_prompt, messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        oai_tools = to_openai_tools(tools)
        if oai_tools:
            body["tools"] = oai_tools
        if reasoning:
            body["reasoning_effort"] = "high" if reasoning == "xhigh" else reasoning
        body.update(options)  # maxTokens/temperature/etc. pass through verbatim
        return body

    async def stream(
        self, *, model: str, system_prompt: str | None, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None, reasoning: str | None = None, **options: Any,
    ) -> AsyncIterator[StreamEvent]:
        body = self._build_body(model, system_prompt, messages, tools, reasoning, options)
        client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout, transport=self._transport)
        try:
            async with client.stream("POST", "/chat/completions", json=body, headers=self._headers()) as resp:
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode("utf-8", "replace")
                    yield _error_event(f"HTTP {resp.status_code}: {detail[:500]}")
                    return
                async for event in self._parse(resp):
                    yield event
        except httpx.HTTPError as exc:  # connection/read errors -> retryable error event
            yield _error_event(f"{type(exc).__name__}: {exc}")
        finally:
            await client.aclose()

    async def _parse(self, resp: httpx.Response) -> AsyncIterator[StreamEvent]:
        """Parse the chat-completions SSE stream into deltas + a terminal message."""
        text_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}  # index -> {id, name, args(str)}
        finish_reason: str | None = None
        usage: dict[str, Any] | None = None

        async for payload in iter_sse(resp):
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    text_parts.append(delta["content"])
                    yield StreamEvent(type="text_delta", delta=delta["content"])
                reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                if reasoning:
                    yield StreamEvent(type="thinking_delta", delta=reasoning)
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tool_calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

        yield self._final(text_parts, tool_calls, finish_reason, usage)

    def _final(
        self, text_parts: list[str], tool_calls: dict[int, dict[str, Any]],
        finish_reason: str | None, usage: dict[str, Any] | None,
    ) -> StreamEvent:
        content: list[dict[str, Any]] = []
        text = "".join(text_parts)
        if text:
            content.append({"type": "text", "text": text})
        for _, tc in sorted(tool_calls.items()):
            try:
                args = json.loads(tc["args"]) if tc["args"].strip() else {}
            except json.JSONDecodeError:
                args = {}
            content.append({"type": "toolCall", "id": tc["id"], "name": tc["name"], "arguments": args})

        stop = _STOP.get(finish_reason or "", "toolUse" if tool_calls else "stop")
        message = AssistantMessage(
            role="assistant", content=content, stopReason=stop, usage=_normalize_usage(usage)
        )
        return StreamEvent(type="done", reason=stop, message=message)

    async def list_models(self) -> list[dict[str, Any]]:
        client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout, transport=self._transport)
        try:
            resp = await client.get("/models", headers=self._headers())
            resp.raise_for_status()
            data = resp.json().get("data") or []
        finally:
            await client.aclose()
        return [{"provider": self._provider, "id": m.get("id")} for m in data if m.get("id")]


def _normalize_usage(usage: dict[str, Any] | None) -> dict[str, int]:
    """OpenAI usage -> our usage dict (``totalTokens`` is what the renderer reads)."""
    if not usage:
        return {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    return {"inputTokens": prompt, "outputTokens": completion, "totalTokens": total}
