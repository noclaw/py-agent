"""Model adapter.

Holds the provider/model/reasoning choice and streams one assistant turn. The agent loop
depends on the small :class:`ModelLike` protocol (so a fake model can stand in for tests),
not on this concrete class.

Routing (Providers Phase 1 — see ``PROVIDERS.md``): an OpenAI-compatible model (built-in
``openai`` et al., or a custom ``.pya/models.json`` entry with ``api: openai-completions``)
streams natively over httpx via :mod:`agent.providers`. Everything else (Anthropic) routes
to the transitional ``pi`` backend, which is started lazily — so an OpenAI-only run never
spawns Node. Phase 2 adds a native Anthropic backend and removes the pi dependency.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Protocol

import httpx
from pi_py_sdk import PiModelClient, StreamEvent

from .config import DEFAULT_MODEL, DEFAULT_PROVIDER, DEFAULT_REASONING
from .providers import NATIVE_APIS, OpenAICompatProvider, Route, route_for
from .providers.auth import resolve_api_key


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
    """Holds model config and streams a turn, routing to a native or the pi backend."""

    def __init__(
        self,
        client: PiModelClient | None,
        *,
        provider: str = DEFAULT_PROVIDER,
        model: str = DEFAULT_MODEL,
        reasoning: str | None = DEFAULT_REASONING,
        spec: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
        **options: Any,
    ) -> None:
        self._client = client
        self._provider = provider
        self._model = model
        self._spec = spec  # full model object for a custom/local model (else None)
        self._reasoning = reasoning
        self._transport = transport  # test seam: injected into the native httpx provider
        self._options = options
        self._pi_started = False

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

        Pass ``spec`` for a custom/local model (a full model object); omit it to select a
        built-in by id. Routing is recomputed per ``stream`` call, so this is cheap.
        """
        self._model = model
        self._spec = spec
        if provider is not None:
            self._provider = provider

    def _route(self) -> Route | None:
        """Resolve how to reach the current model, or ``None`` to use the pi backend."""
        if self._spec is not None:
            known = route_for(self._provider, self._model)
            return Route(
                api=self._spec.get("api", "openai-completions"),
                base_url=self._spec.get("baseUrl") or (known.base_url if known else ""),
                env_var=known.env_var if known else None,
            )
        return route_for(self._provider, self._model)

    async def _ensure_pi(self) -> None:
        if self._client is None:
            raise RuntimeError(f"No pi backend available for {self.name}")
        if not self._pi_started:
            await self._client.start()
            self._pi_started = True

    async def list_models(self, provider: str | None = None) -> list[dict[str, Any]]:
        """List the models the (transitional) pi catalog knows about. Starts pi lazily."""
        await self._ensure_pi()
        return await self._client.list_models(provider)  # type: ignore[union-attr]

    async def stream(
        self,
        *,
        system_prompt: str | None = None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        route = self._route()
        if route is not None and route.api in NATIVE_APIS:
            provider_impl = OpenAICompatProvider(
                base_url=route.base_url,
                api_key=resolve_api_key(route, self._spec),
                provider=self._provider,
                transport=self._transport,
            )
            async for event in provider_impl.stream(
                model=self._model, system_prompt=system_prompt, messages=messages,
                tools=tools, reasoning=self._reasoning, **self._options,
            ):
                yield event
            return

        # Transitional pi backend (Anthropic and any non-native provider).
        await self._ensure_pi()
        target: str | dict[str, Any] = self._spec if self._spec is not None else self._model
        options = dict(self._options)
        if self._spec is not None and self._spec.get("apiKey") and "apiKey" not in options:
            options["apiKey"] = self._spec["apiKey"]
        async for event in self._client.stream(  # type: ignore[union-attr]
            provider=self._provider, model=target, messages=messages,
            system_prompt=system_prompt, tools=tools, reasoning=self._reasoning, **options,
        ):
            yield event


@asynccontextmanager
async def open_model(
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    reasoning: str | None = DEFAULT_REASONING,
    spec: dict[str, Any] | None = None,
    transport: httpx.BaseTransport | None = None,
    client_kwargs: dict[str, Any] | None = None,
    **options: Any,
) -> AsyncIterator[Model]:
    """Yield a :class:`Model`, cleaning up the pi backend if it was started.

        async with open_model(provider="openai", model="gpt-5.1") as model:
            async for event in run_agent(model, tools, history):
                ...

    The pi backend starts lazily (only when a non-native model streams), so OpenAI-compatible
    runs spawn no Node subprocess. ``spec`` selects a custom/local model.
    """
    client = PiModelClient(**(client_kwargs or {}))
    try:
        yield Model(
            client, provider=provider, model=model, reasoning=reasoning, spec=spec,
            transport=transport, **options,
        )
    finally:
        await client.stop()  # safe no-op if pi was never started
