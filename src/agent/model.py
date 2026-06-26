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
        spec: dict[str, Any] | None = None,
        **options: Any,
    ) -> None:
        self._client = client
        self._provider = provider
        self._model = model
        self._spec = spec  # full model object for a custom/local model (else None)
        self._reasoning = reasoning
        self._options = options

    @property
    def name(self) -> str:
        return f"{self._provider}/{self._model}"

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def set_model(
        self, model: str, provider: str | None = None, *, spec: dict[str, Any] | None = None
    ) -> None:
        """Switch the model (and optionally provider) for subsequent turns.

        Cheap: the underlying client streams any model, so this just changes which
        provider/model the next ``stream`` call targets. Pass ``spec`` for a custom/local
        model (a full pi-ai model object); omit it to select a built-in by id.
        """
        self._model = model
        self._spec = spec
        if provider is not None:
            self._provider = provider

    async def list_models(self, provider: str | None = None) -> list[dict[str, Any]]:
        """List the models pi-ai's built-in catalog knows about (optionally one provider)."""
        return await self._client.list_models(provider)

    async def stream(
        self,
        *,
        system_prompt: str | None = None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        # A custom model streams as a full spec object; a built-in streams by id.
        target: str | dict[str, Any] = self._spec if self._spec is not None else self._model
        options = dict(self._options)
        # A custom/local endpoint's key lives in its spec; pi-ai resolves credentials from
        # the stream options (caller key > env var > OAuth), so surface it there.
        if self._spec is not None and self._spec.get("apiKey") and "apiKey" not in options:
            options["apiKey"] = self._spec["apiKey"]
        async for event in self._client.stream(
            provider=self._provider,
            model=target,
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            reasoning=self._reasoning,
            **options,
        ):
            yield event


@asynccontextmanager
async def open_model(
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    reasoning: str | None = DEFAULT_REASONING,
    spec: dict[str, Any] | None = None,
    client_kwargs: dict[str, Any] | None = None,
    **options: Any,
) -> AsyncIterator[Model]:
    """Create and start a ``PiModelClient``, yield a :class:`Model`, and clean up.

        async with open_model(provider="anthropic", model="claude-sonnet-4-6") as model:
            async for event in run_agent(model, tools, history):
                ...

    Pass ``spec`` (a full pi-ai model object) for a custom/local model; ``provider``/``model``
    then name it for display/sessions while ``spec`` is what's streamed.
    """
    client = PiModelClient(**(client_kwargs or {}))
    await client.start()
    try:
        yield Model(client, provider=provider, model=model, reasoning=reasoning, spec=spec, **options)
    finally:
        await client.stop()
