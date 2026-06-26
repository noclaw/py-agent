"""The native provider interface.

A ``Provider`` turns a wire context (system prompt + messages + tools) into a stream of
:class:`StreamEvent`s, and can list a provider's models. This is the extension point: to
support a transport we don't ship (Bedrock, Vertex, …), implement this protocol and register
the model under a custom ``api`` id via ``.pya/models.json``. See ``PROVIDERS.md``.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol

from ..wire import StreamEvent

__all__ = ["Provider"]


class Provider(Protocol):
    """Streams one assistant turn and lists models for one API flavor."""

    def stream(
        self,
        *,
        model: str,
        system_prompt: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        reasoning: str | None = None,
        **options: Any,
    ) -> AsyncIterator[StreamEvent]: ...

    async def list_models(self) -> list[dict[str, Any]]: ...
