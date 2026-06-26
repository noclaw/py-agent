"""Anthropic Messages provider — ``POST /v1/messages`` over httpx (Providers Phase 2).

Native streaming for Claude: text + extended thinking (with signature round-trip) + tool
use, normalized into the same ``StreamEvent`` / ``AssistantMessage`` the loop already
consumes. See ``PROVIDERS.md``.

Auth: an API key on ``x-api-key`` (env ``ANTHROPIC_API_KEY`` or a custom spec key), or an
OAuth bearer token (Claude Pro/Max — see :mod:`agent.providers.oauth`) on ``Authorization``
plus the OAuth beta header.

Thinking is opt-in via ``reasoning`` (the ``--reasoning`` flag): when set, the request asks
for adaptive thinking at the mapped effort, and returned ``thinking`` blocks are preserved
**with their signature** so the next turn replays them verbatim (the API requires this).
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from ..wire import AssistantMessage, StreamEvent
from .http import DEFAULT_TIMEOUT, iter_sse

__all__ = ["AnthropicProvider"]

ANTHROPIC_VERSION = "2023-06-01"
OAUTH_BETA = "oauth-2025-04-20"
DEFAULT_MAX_TOKENS = 16384

#: Anthropic stop_reason -> our stopReason vocabulary (the loop reads tool calls from
#: content; it only special-cases "error"/"aborted").
_STOP = {"end_turn": "stop", "max_tokens": "length", "tool_use": "toolUse",
         "stop_sequence": "stop", "refusal": "refusal", "pause_turn": "stop"}

#: --reasoning level -> Anthropic effort (budget_tokens is removed on current models).
_EFFORT = {"minimal": "low", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh"}


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert py-agent wire messages to Anthropic messages (coalescing same-role runs)."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "content": [{"type": "text", "text": _text_of(m.get("content"))}]})
        elif role == "toolResult":
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": m.get("toolCallId", ""),
                "content": _text_of(m.get("content")),
            }
            if m.get("isError"):
                block["is_error"] = True
            out.append({"role": "user", "content": [block]})
        elif role == "assistant":
            out.append({"role": "assistant", "content": _assistant_blocks(m.get("content") or [])})
    return _coalesce(out)


def _assistant_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for b in blocks:
        t = b.get("type")
        if t == "text":
            converted.append({"type": "text", "text": b.get("text", "")})
        elif t == "thinking":
            # Preserve the signature — Anthropic requires it to replay a thinking block.
            tb: dict[str, Any] = {"type": "thinking", "thinking": b.get("thinking", "")}
            if b.get("signature"):
                tb["signature"] = b["signature"]
            converted.append(tb)
        elif t == "redacted_thinking":
            converted.append({"type": "redacted_thinking", "data": b.get("data", "")})
        elif t == "toolCall":
            converted.append({"type": "tool_use", "id": b.get("id", ""), "name": b.get("name", ""),
                              "input": b.get("arguments") or {}})
    return converted


def _coalesce(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive same-role messages (Anthropic groups tool_results into one turn)."""
    merged: list[dict[str, Any]] = []
    for m in messages:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"].extend(m["content"])
        else:
            merged.append({"role": m["role"], "content": list(m["content"])})
    return merged


def _error_event(message: str) -> StreamEvent:
    failed = AssistantMessage(role="assistant", content=[], stopReason="error", errorMessage=message)
    return StreamEvent(type="error", reason="error", error=failed)


class AnthropicProvider:
    """Streams from Anthropic's ``/v1/messages`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.anthropic.com/v1",
        api_key: str | None = None,
        oauth_token: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._oauth_token = oauth_token
        self._max_tokens = max_tokens
        self._transport = transport
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json", "anthropic-version": ANTHROPIC_VERSION}
        if self._oauth_token:
            headers["authorization"] = f"Bearer {self._oauth_token}"
            headers["anthropic-beta"] = OAUTH_BETA
        elif self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def _build_body(
        self, model: str, system_prompt: str | None, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None, reasoning: str | None, options: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": int(options.pop("maxTokens", self._max_tokens)),
            "messages": to_anthropic_messages(messages),
            "stream": True,
        }
        if system_prompt:
            body["system"] = system_prompt
        if tools:
            body["tools"] = [
                {"name": t["name"], "description": t.get("description", ""),
                 "input_schema": t.get("parameters", {})}
                for t in tools
            ]
        if reasoning:
            # Adaptive thinking + effort (budget_tokens is removed on current Claude models);
            # display:summarized so reasoning streams visibly for the renderer.
            body["thinking"] = {"type": "adaptive", "display": "summarized"}
            body["output_config"] = {"effort": _EFFORT.get(reasoning, "medium")}
        body.update(options)
        return body

    async def stream(
        self, *, model: str, system_prompt: str | None, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None, reasoning: str | None = None, **options: Any,
    ) -> AsyncIterator[StreamEvent]:
        body = self._build_body(model, system_prompt, messages, tools, reasoning, dict(options))
        client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout, transport=self._transport)
        try:
            async with client.stream("POST", "/messages", json=body, headers=self._headers()) as resp:
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode("utf-8", "replace")
                    yield _error_event(f"HTTP {resp.status_code}: {detail[:500]}")
                    return
                async for event in self._parse(resp):
                    yield event
        except httpx.HTTPError as exc:
            yield _error_event(f"{type(exc).__name__}: {exc}")
        finally:
            await client.aclose()

    async def _parse(self, resp: httpx.Response) -> AsyncIterator[StreamEvent]:
        """Parse the Messages SSE event stream into deltas + a terminal message."""
        blocks: dict[int, dict[str, Any]] = {}  # index -> in-progress block
        order: list[int] = []
        stop_reason: str | None = None
        usage: dict[str, Any] = {}

        async for payload in iter_sse(resp):
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            etype = ev.get("type")

            if etype == "message_start":
                usage.update((ev.get("message") or {}).get("usage") or {})
            elif etype == "error":
                yield _error_event(str((ev.get("error") or {}).get("message") or "stream error"))
                return
            elif etype == "content_block_start":
                idx = ev.get("index", 0)
                cb = ev.get("content_block") or {}
                order.append(idx)
                if cb.get("type") == "tool_use":
                    blocks[idx] = {"type": "tool_use", "id": cb.get("id", ""), "name": cb.get("name", ""), "json": ""}
                elif cb.get("type") == "thinking":
                    blocks[idx] = {"type": "thinking", "thinking": "", "signature": ""}
                elif cb.get("type") == "redacted_thinking":
                    blocks[idx] = {"type": "redacted_thinking", "data": cb.get("data", "")}
                else:
                    blocks[idx] = {"type": "text", "text": ""}
            elif etype == "content_block_delta":
                idx = ev.get("index", 0)
                delta = ev.get("delta") or {}
                dtype = delta.get("type")
                slot = blocks.setdefault(idx, {"type": "text", "text": ""})
                if dtype == "text_delta":
                    slot["text"] = slot.get("text", "") + delta.get("text", "")
                    yield StreamEvent(type="text_delta", delta=delta.get("text", ""), contentIndex=idx)
                elif dtype == "thinking_delta":
                    slot["thinking"] = slot.get("thinking", "") + delta.get("thinking", "")
                    yield StreamEvent(type="thinking_delta", delta=delta.get("thinking", ""), contentIndex=idx)
                elif dtype == "signature_delta":
                    slot["signature"] = slot.get("signature", "") + delta.get("signature", "")
                elif dtype == "input_json_delta":
                    slot["json"] = slot.get("json", "") + delta.get("partial_json", "")
            elif etype == "message_delta":
                stop_reason = (ev.get("delta") or {}).get("stop_reason") or stop_reason
                usage.update(ev.get("usage") or {})

        yield self._final(blocks, order, stop_reason, usage)

    def _final(
        self, blocks: dict[int, dict[str, Any]], order: list[int],
        stop_reason: str | None, usage: dict[str, Any],
    ) -> StreamEvent:
        content: list[dict[str, Any]] = []
        for idx in order:
            b = blocks.get(idx) or {}
            if b.get("type") == "text" and b.get("text"):
                content.append({"type": "text", "text": b["text"]})
            elif b.get("type") == "thinking":
                content.append({"type": "thinking", "thinking": b.get("thinking", ""),
                                "signature": b.get("signature", "")})
            elif b.get("type") == "redacted_thinking":
                content.append({"type": "redacted_thinking", "data": b.get("data", "")})
            elif b.get("type") == "tool_use":
                try:
                    args = json.loads(b["json"]) if b.get("json", "").strip() else {}
                except json.JSONDecodeError:
                    args = {}
                content.append({"type": "toolCall", "id": b.get("id", ""), "name": b.get("name", ""), "arguments": args})

        stop = _STOP.get(stop_reason or "", "stop")
        message = AssistantMessage(role="assistant", content=content, stopReason=stop, usage=_normalize_usage(usage))
        return StreamEvent(type="done", reason=stop, message=message)

    async def list_models(self) -> list[dict[str, Any]]:
        client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout, transport=self._transport)
        try:
            resp = await client.get("/models", headers=self._headers())
            resp.raise_for_status()
            data = resp.json().get("data") or []
        finally:
            await client.aclose()
        return [{"provider": "anthropic", "id": m.get("id")} for m in data if m.get("id")]


def _normalize_usage(usage: dict[str, Any]) -> dict[str, int]:
    if not usage:
        return {}
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    return {
        "inputTokens": inp, "outputTokens": out,
        "cacheReadTokens": cache_read, "cacheWriteTokens": cache_write,
        "totalTokens": inp + out + cache_read + cache_write,
    }
