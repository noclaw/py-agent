"""Model adapter.

Holds the provider/model/reasoning choice and streams one assistant turn over the native
provider layer (:mod:`agent.providers`) — no Node, no shim. The agent loop depends on the
small :class:`ModelLike` protocol (so a fake model can stand in for tests), not on this
concrete class.

Routing is by the model's ``api``: ``openai-completions`` (OpenAI + local/OpenAI-compatible)
and ``anthropic-messages`` (Claude) stream natively. A model's ``api``/``baseUrl`` come from
the static catalog (built-ins) or a ``.pya/models.json`` spec (custom/local). See
``PROVIDERS.md``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Protocol

import httpx

from .config import DEFAULT_MODEL, DEFAULT_PROVIDER, DEFAULT_REASONING
from .providers import (
    AnthropicProvider,
    OpenAICompatProvider,
    Provider,
    ProviderError,
    Route,
    route_for,
)
from .providers.auth import resolve_api_key
from .wire import StreamEvent


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
    """Holds model config and streams a turn via the native provider for its API flavor."""

    def __init__(
        self,
        *,
        provider: str = DEFAULT_PROVIDER,
        model: str = DEFAULT_MODEL,
        reasoning: str | None = DEFAULT_REASONING,
        spec: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
        **options: Any,
    ) -> None:
        self._provider = provider
        self._model = model
        self._spec = spec  # full model object for a custom/local model (else None)
        self._reasoning = reasoning
        self._transport = transport  # test seam: injected into the native httpx provider
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
        """Switch the model (and optionally provider) for subsequent turns. Pass ``spec`` for
        a custom/local model; omit it to select a built-in by id. Routing is per-stream."""
        self._model = model
        self._spec = spec
        if provider is not None:
            self._provider = provider

    def _route(self) -> Route | None:
        """Resolve how to reach the current model, or ``None`` if unknown."""
        if self._spec is not None:
            known = route_for(self._provider, self._model)
            return Route(
                api=self._spec.get("api", "openai-completions"),
                base_url=self._spec.get("baseUrl") or (known.base_url if known else ""),
                env_var=known.env_var if known else None,
            )
        return route_for(self._provider, self._model)

    def _provider_impl(self) -> Provider:
        route = self._route()
        if route is None:
            raise ProviderError(
                f"Don't know how to reach {self.name}. Add it to ~/.pya/models.json "
                f"(provider with baseUrl + api), or pick a known provider."
            )
        api_key = resolve_api_key(route, self._spec, provider=self._provider)
        if route.api == "openai-completions":
            return OpenAICompatProvider(
                base_url=route.base_url, api_key=api_key, provider=self._provider,
                transport=self._transport,
            )
        if route.api == "anthropic-messages":
            kwargs: dict[str, Any] = {"base_url": route.base_url, "transport": self._transport}
            if self._spec and self._spec.get("maxTokens"):
                kwargs["max_tokens"] = int(self._spec["maxTokens"])
            return AnthropicProvider(api_key=api_key, **kwargs)
        raise ProviderError(f"No native provider for api {route.api!r} ({self.name}).")

    async def stream(
        self,
        *,
        system_prompt: str | None = None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        provider = self._provider_impl()
        async for event in provider.stream(
            model=self._model, system_prompt=system_prompt, messages=messages,
            tools=tools, reasoning=self._reasoning, **self._options,
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
    **options: Any,
) -> AsyncIterator[Model]:
    """Yield a :class:`Model`. No subprocess to manage — the native providers open a
    short-lived httpx client per stream.

        async with open_model(provider="anthropic", model="claude-opus-4-8") as model:
            async for event in run_agent(model, tools, history):
                ...

    ``spec`` selects a custom/local model (a full model object with ``api``/``baseUrl``).
    """
    yield Model(
        provider=provider, model=model, reasoning=reasoning, spec=spec,
        transport=transport, **options,
    )
