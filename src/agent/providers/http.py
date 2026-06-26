"""Shared HTTP/SSE helpers for native providers.

A thin layer over ``httpx`` async streaming: iterate Server-Sent Events as parsed ``data:``
payloads. Kept separate so the OpenAI-compatible and (Phase 2) Anthropic backends share one
streaming implementation.
"""

from __future__ import annotations

from typing import AsyncIterator

import httpx

__all__ = ["iter_sse", "DEFAULT_TIMEOUT"]

#: Generous read timeout: a streaming completion may pause between tokens.
DEFAULT_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=15.0)


async def iter_sse(response: httpx.Response) -> AsyncIterator[str]:
    """Yield the ``data:`` payload of each SSE event (excluding the ``[DONE]`` sentinel).

    Lines that aren't ``data:`` (comments, ``event:``/``id:`` fields, blank separators) are
    ignored — enough for the OpenAI and Anthropic event streams.
    """
    async for line in response.aiter_lines():
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            return
        if payload:
            yield payload
