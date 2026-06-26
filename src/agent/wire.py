"""Native message & stream-event types — the project's own model-layer contract.

These replace the types previously imported from ``pi_py_sdk`` (Providers Phase 2 — see
``PROVIDERS.md``). Shapes deliberately mirror what pi-ai exposed so the loop, renderer,
sessions, and tests are unchanged apart from their import line.

- :class:`AssistantMessage` — one assistant turn, kept verbatim so it round-trips back to
  the provider (preserving e.g. Anthropic thinking ``signature``s). ``extra="allow"`` keeps
  any provider field we don't model.
- :class:`StreamEvent` — one streamed delta or terminal event. The loop consumes the
  terminal event's :pyattr:`StreamEvent.final_message`; the renderer consumes ``type`` +
  ``delta``.
- :class:`ToolCall` — a tool-call content block (id/name/arguments).

Content blocks (items of ``AssistantMessage.content``) are plain dicts:
``{"type": "text", "text": ...}``, ``{"type": "thinking", "thinking": ..., "signature": ...}``,
``{"type": "toolCall", "id": ..., "name": ..., "arguments": {...}}``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["AssistantMessage", "StreamEvent", "ToolCall"]


class ToolCall(BaseModel):
    """A tool-call content block."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class AssistantMessage(BaseModel):
    """A single assistant turn, replayed verbatim on subsequent requests."""

    model_config = ConfigDict(extra="allow")

    role: str = "assistant"
    content: list[Any] = Field(default_factory=list)
    stopReason: str | None = None
    usage: dict[str, Any] | None = None
    errorMessage: str | None = None


@dataclass
class StreamEvent:
    """One event from a model stream.

    ``type`` is one of: ``text_delta``, ``thinking_delta``, ``toolcall_end``, ``done``,
    ``error``. ``done``/``error`` are terminal and carry the assembled assistant message in
    ``message``/``error`` respectively.
    """

    type: str
    delta: str | None = None
    contentIndex: int | None = None
    toolCall: ToolCall | None = None
    message: AssistantMessage | None = None
    reason: str | None = None
    error: AssistantMessage | None = None

    @property
    def is_terminal(self) -> bool:
        return self.type in ("done", "error")

    @property
    def final_message(self) -> AssistantMessage | None:
        if self.type == "done":
            return self.message
        if self.type == "error":
            return self.error
        return None
