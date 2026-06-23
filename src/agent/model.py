"""Model adapter.

A thin wrapper over :class:`pi_py_sdk.model.PiModelClient` that holds the
provider/model/reasoning choice and streams one assistant turn. The agent loop depends on
the small :class:`ModelLike` protocol (so a fake model can stand in for tests), not on
this concrete class.

Credential resolution lives entirely in pi-ai / the shim (caller key > provider env var >
``~/.pi/agent/auth.json`` OAuth) — there's nothing to do here but pass options through.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Protocol

from pi_py_sdk import PiModelClient, StreamEvent

from .config import DEFAULT_MODEL, DEFAULT_PROVIDER, DEFAULT_REASONING


class ModelLike(Protocol):
    """What the loop needs from a model: stream one turn from a wire context."""

    def stream(
        self,
        *,
        system_prompt: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[StreamEvent]: ...


class Model:
    """Holds model config and streams a turn via a (started) ``PiModelClient``."""

    def __init__(
        self,
        client: PiModelClient,
        *,
        provider: str = DEFAULT_PROVIDER,
        model: str = DEFAULT_MODEL,
        reasoning: str | None = DEFAULT_REASONING,
        **options: Any,
    ) -> None:
        self._client = client
        self._provider = provider
        self._model = model
        self._reasoning = reasoning
        self._options = options

    @property
    def name(self) -> str:
        return f"{self._provider}/{self._model}"

    async def stream(
        self,
        *,
        system_prompt: str | None = None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        async for event in self._client.stream(
            provider=self._provider,
            model=self._model,
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            reasoning=self._reasoning,
            **self._options,
        ):
            yield event


@asynccontextmanager
async def open_model(
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    reasoning: str | None = DEFAULT_REASONING,
    client_kwargs: dict[str, Any] | None = None,
    **options: Any,
) -> AsyncIterator[Model]:
    """Create and start a ``PiModelClient``, yield a :class:`Model`, and clean up.

        async with open_model(provider="anthropic", model="claude-sonnet-4-6") as model:
            async for event in run_agent(model, tools, history):
                ...
    """
    client = PiModelClient(**(client_kwargs or {}))
    await client.start()
    try:
        yield Model(client, provider=provider, model=model, reasoning=reasoning, **options)
    finally:
        await client.stop()
