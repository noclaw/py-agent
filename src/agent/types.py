"""Core data types for the agent.

Port target: ``packages/agent/src/types.ts``.

Three things live here:

1. **Messages** — the in-memory conversation (:class:`UserMessage`,
   :class:`AssistantMessage`, :class:`ToolResultMessage`) and :func:`to_llm_messages`,
   the converter to the pi-ai wire format that
   :meth:`pi_py_sdk.model.PiModelClient.stream` consumes (Pi calls this ``convertToLlm``).
2. **The ``Tool`` protocol** — what a tool is (name, description, a Pydantic parameter
   model that becomes JSON Schema, and an ``execute`` coroutine), plus :class:`ToolResult`.
3. **Agent events** — the small dataclasses the loop emits for the renderer.

Design note: internal data uses plain ``dataclass``es (readable, no ceremony); the only
place we reach for Pydantic is tool **parameters**, where we genuinely want JSON-Schema
generation and validation at the model boundary.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, ClassVar, Union

from pi_py_sdk import AssistantMessage as LlmAssistantMessage
from pi_py_sdk import StreamEvent
from pydantic import BaseModel

__all__ = [
    "now_ms",
    "UserMessage",
    "AssistantMessage",
    "ToolResultMessage",
    "AgentMessage",
    "user_message",
    "tool_result_message",
    "message_to_wire",
    "message_from_wire",
    "to_llm_messages",
    "ToolResult",
    "Tool",
    "AgentEvent",
    "AgentStart",
    "TurnStart",
    "AssistantDelta",
    "AssistantDone",
    "ToolStart",
    "ToolOutput",
    "ToolEnd",
    "TurnEnd",
    "AgentEnd",
]


def now_ms() -> int:
    """Current Unix time in milliseconds (the ``timestamp`` pi-ai messages carry)."""
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
#
# A turn of conversation is a list of these. The assistant message is kept as the *exact*
# object pi-ai streamed back (:class:`pi_py_sdk.AssistantMessage`) so it can be replayed
# verbatim — preserving thinking/tool signatures that providers require for multi-turn
# continuity. User and tool-result messages we construct ourselves, so they're plain
# dataclasses with a ``to_wire`` method.


@dataclass
class UserMessage:
    """A user turn. ``content`` is plain text (image support is a later phase)."""

    content: str
    timestamp: int = field(default_factory=now_ms)
    role: ClassVar[str] = "user"

    def to_wire(self) -> dict[str, Any]:
        return {"role": "user", "content": self.content, "timestamp": self.timestamp}


@dataclass
class ToolResultMessage:
    """The result of one tool call, fed back to the model on the next turn."""

    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
    timestamp: int = field(default_factory=now_ms)
    role: ClassVar[str] = "toolResult"

    def to_wire(self) -> dict[str, Any]:
        return {
            "role": "toolResult",
            "toolCallId": self.tool_call_id,
            "toolName": self.tool_name,
            # pi-ai expects content as a list of blocks.
            "content": [{"type": "text", "text": self.content}],
            "isError": self.is_error,
            "timestamp": self.timestamp,
        }


#: The assistant message is pi-ai's own model, replayed verbatim (see note above).
AssistantMessage = LlmAssistantMessage

#: Anything that can appear in the conversation history.
AgentMessage = Union[UserMessage, "AssistantMessage", ToolResultMessage]


def user_message(content: str) -> UserMessage:
    """Build a user message (convenience)."""
    return UserMessage(content=content)


def tool_result_message(
    tool_call_id: str, tool_name: str, content: str, *, is_error: bool = False
) -> ToolResultMessage:
    """Build a tool-result message (convenience)."""
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=tool_name, content=content, is_error=is_error
    )


def _assistant_to_wire(message: "AssistantMessage") -> dict[str, Any]:
    """Serialize a streamed assistant message back to a wire dict, full fidelity."""
    if isinstance(message, BaseModel):
        # camelCase field names are stored verbatim by pi_py_sdk, and extra="allow"
        # preserves provider signatures; keep nulls out to mirror what pi-ai sent.
        return message.model_dump(exclude_none=True)
    if isinstance(message, dict):
        return message
    raise TypeError(f"Unexpected assistant message type: {type(message)!r}")


def message_to_wire(message: AgentMessage) -> dict[str, Any]:
    """Serialize one history message to its pi-ai wire dict (used by the model and by
    session persistence)."""
    if isinstance(message, (UserMessage, ToolResultMessage)):
        return message.to_wire()
    return _assistant_to_wire(message)


def _text_of(content: Any) -> str:
    """Pull plain text out of a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def message_from_wire(data: dict[str, Any]) -> AgentMessage:
    """Reconstruct a history message from its wire dict (inverse of :func:`message_to_wire`)."""
    role = data.get("role")
    timestamp = data.get("timestamp") or now_ms()
    if role == "user":
        return UserMessage(content=_text_of(data.get("content", "")), timestamp=timestamp)
    if role == "toolResult":
        return ToolResultMessage(
            tool_call_id=data.get("toolCallId", ""),
            tool_name=data.get("toolName", ""),
            content=_text_of(data.get("content", "")),
            is_error=bool(data.get("isError")),
            timestamp=timestamp,
        )
    return AssistantMessage.model_validate(data)  # assistant: full fidelity


def to_llm_messages(history: list[AgentMessage]) -> list[dict[str, Any]]:
    """Convert conversation history to the pi-ai wire messages the model consumes.

    This is the ``convertToLlm`` seam: it's where in-memory message objects become the
    list passed to :meth:`pi_py_sdk.model.PiModelClient.stream`.
    """
    return [message_to_wire(message) for message in history]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """The outcome of a tool execution.

    ``content`` is the text shown to the model; ``details`` is optional structured data
    for the renderer (e.g. a diff); ``is_error`` marks a failure.
    """

    content: str
    details: Any = None
    is_error: bool = False


#: A callback a streaming tool (e.g. bash) calls with incremental output.
ToolUpdateCallback = Callable[[str], None]


class Tool(ABC):
    """Base class for a tool the agent can call.

    Subclasses set the class attributes and implement :meth:`execute`. ``parameters`` is a
    Pydantic model describing the arguments; its JSON Schema is what the model sees, and
    the loop validates raw arguments against it before calling :meth:`execute`.
    """

    #: Tool name the model uses to call it (snake_case, stable).
    name: ClassVar[str]
    #: One/two sentence description shown to the model.
    description: ClassVar[str]
    #: Pydantic model for the tool's arguments.
    parameters: ClassVar[type[BaseModel]]
    #: One-line "Available tools" entry for the system prompt (``None`` = omit).
    prompt_snippet: ClassVar[str | None] = None
    #: Extra guideline bullets contributed to the system prompt.
    prompt_guidelines: ClassVar[tuple[str, ...]] = ()
    #: "parallel" (default) or "sequential" — forces serialized execution in a batch.
    execution_mode: ClassVar[str] = "parallel"

    @abstractmethod
    async def execute(
        self, args: BaseModel, *, on_update: ToolUpdateCallback | None = None
    ) -> ToolResult:
        """Run the tool with validated ``args`` and return a :class:`ToolResult`.

        ``on_update`` may be called with incremental output for streaming tools.
        Cancellation is cooperative via ``asyncio`` task cancellation — use ``try/finally``
        to clean up (e.g. kill a subprocess).
        """

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        """JSON Schema for the tool's parameters (from the Pydantic model)."""
        schema = cls.parameters.model_json_schema()
        schema.pop("title", None)  # the model doesn't need the Python class name
        return schema

    @classmethod
    def to_wire(cls) -> dict[str, Any]:
        """The tool definition pi-ai sends to the model."""
        return {"name": cls.name, "description": cls.description, "parameters": cls.json_schema()}


def tools_to_wire(tools: list[Tool] | list[type[Tool]]) -> list[dict[str, Any]]:
    """Convert a list of tools (instances or classes) to wire definitions."""
    return [tool.to_wire() for tool in tools]


# ---------------------------------------------------------------------------
# Agent events (emitted by the loop, consumed by the renderer)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentEvent:
    """Base class for everything the loop emits."""


@dataclass(frozen=True)
class AgentStart(AgentEvent):
    """The run began."""


@dataclass(frozen=True)
class TurnStart(AgentEvent):
    """A new turn (one model call + any tool calls it makes) began."""

    index: int


@dataclass(frozen=True)
class AssistantDelta(AgentEvent):
    """A streaming chunk of the assistant message (text/thinking/tool-call delta).

    Wraps the raw pi-ai :class:`~pi_py_sdk.StreamEvent` so the renderer can show live
    output without re-deriving it.
    """

    event: StreamEvent


@dataclass(frozen=True)
class AssistantDone(AgentEvent):
    """The assistant message for this turn is complete."""

    message: "AssistantMessage"


@dataclass(frozen=True)
class ToolStart(AgentEvent):
    """A tool call started executing."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolOutput(AgentEvent):
    """Incremental output from a running tool (e.g. streamed bash stdout)."""

    tool_call_id: str
    tool_name: str
    chunk: str


@dataclass(frozen=True)
class ToolEnd(AgentEvent):
    """A tool call finished."""

    tool_call_id: str
    tool_name: str
    result: ToolResult


@dataclass(frozen=True)
class TurnEnd(AgentEvent):
    """A turn finished."""

    index: int


@dataclass(frozen=True)
class AgentEnd(AgentEvent):
    """The run finished. ``reason`` is "completed", "error", or "aborted"."""

    reason: str = "completed"


#: Anything a loop event listener might receive. (Loops are async generators of these.)
AgentEventHandler = Callable[[AgentEvent], Union[None, Awaitable[None]]]
