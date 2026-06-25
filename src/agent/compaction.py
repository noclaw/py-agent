"""Context compaction — summarize old history when it nears the context window.

Port target: ``packages/agent/src/harness/compaction/``.

The loop exposes a ``transform_context`` seam (see :func:`agent.loop.run_agent`): a callback
run once per turn, *before* streaming, that may return a replacement history. Compaction is
the canonical use of that seam — it keeps the conversation under the model's context window
without the loop knowing anything about summarization.

The strategy here is deliberately simple (Pi's branch summarization is much more advanced):

1. Estimate the current token footprint from the most recent assistant message's reported
   ``usage`` (falling back to a rough char-based estimate).
2. If it exceeds ``threshold`` × the context window, summarize everything except the most
   recent ``keep_recent`` messages into a single synthetic user message, then keep the tail.

The split point is nudged backwards so it never lands on a tool-result message — that would
orphan it from the assistant tool-call that produced it, which some providers reject.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from .types import (
    AgentEvent,
    AgentMessage,
    CompactionEnd,
    CompactionStart,
    ToolResultMessage,
    UserMessage,
    message_to_wire,
    to_llm_messages,
    user_message,
)

if TYPE_CHECKING:
    from .model import ModelLike

__all__ = ["CompactionConfig", "Compactor", "estimate_tokens"]

#: Emit channel handed to a ``transform_context`` callback by the loop.
EmitFn = Callable[[AgentEvent], None]

_SUMMARY_SYSTEM_PROMPT = (
    "You are compacting a coding-agent conversation so it fits in a smaller context window. "
    "Summarize the conversation so far for your future self: the user's goal, key decisions, "
    "files and commands touched, what has been done, and what remains. Be concise but keep "
    "every detail needed to continue the task without re-reading the originals. Output only "
    "the summary."
)


def estimate_tokens(history: list[AgentMessage]) -> int:
    """Best-effort token estimate for ``history``.

    Prefers the ``totalTokens`` the most recent assistant message reported (that already
    reflects the whole prompt the provider tokenized); otherwise falls back to ~4 chars per
    token over the serialized messages.
    """
    for message in reversed(history):
        usage = getattr(message, "usage", None)
        if isinstance(usage, dict):
            total = usage.get("totalTokens")
            if total:
                return int(total)
            parts = usage.get("inputTokens", 0) + usage.get("outputTokens", 0)
            if parts:
                return int(parts)
    chars = sum(len(str(message_to_wire(m))) for m in history)
    return chars // 4


@dataclass(frozen=True)
class CompactionConfig:
    """Tuning for :class:`Compactor`.

    Args:
        max_tokens: the model's context window (compaction targets a fraction of this).
        threshold: compact once the estimate exceeds ``threshold`` × ``max_tokens``.
        keep_recent: messages at the tail kept verbatim (the rest are summarized).
        max_summary_turns: safety cap on the summarization model call.
    """

    max_tokens: int = 200_000
    threshold: float = 0.8
    keep_recent: int = 6
    max_summary_turns: int = 1


def _safe_split(history: list[AgentMessage], keep_recent: int) -> int:
    """Index that splits ``history`` into (head to summarize, tail to keep).

    Starts ``keep_recent`` from the end, then walks back so the tail never *starts* on a
    tool-result (which would be orphaned from its tool call once the head is summarized).
    """
    i = max(0, len(history) - keep_recent)
    while i > 0 and isinstance(history[i], ToolResultMessage):
        i -= 1
    return i


class Compactor:
    """Summarizes old history with a model when the conversation grows too large.

    Wire it into the loop via :meth:`transform`::

        compactor = Compactor(model, CompactionConfig(max_tokens=200_000))
        async for ev in run_agent(model, tools, history, transform_context=compactor.transform):
            ...
    """

    def __init__(self, model: "ModelLike", config: CompactionConfig | None = None) -> None:
        self._model = model
        self.config = config or CompactionConfig()

    def should_compact(self, history: list[AgentMessage]) -> bool:
        if len(history) <= self.config.keep_recent + 1:
            return False
        return estimate_tokens(history) >= self.config.threshold * self.config.max_tokens

    async def transform(
        self, history: list[AgentMessage], emit: EmitFn
    ) -> list[AgentMessage] | None:
        """``transform_context`` callback: compact if over threshold, else leave unchanged.

        Returns the new history (which the loop swaps in) or ``None`` for no change.
        """
        if not self.should_compact(history):
            return None

        split = _safe_split(history, self.config.keep_recent)
        if split <= 0:
            return None  # nothing safe to summarize yet
        head, tail = history[:split], history[split:]

        emit(CompactionStart(before_messages=len(history)))
        summary = await self._summarize(head)
        new_history: list[AgentMessage] = [
            user_message(f"[Summary of earlier conversation]\n{summary}"),
            *tail,
        ]
        emit(CompactionEnd(before_messages=len(history), after_messages=len(new_history)))
        return new_history

    async def _summarize(self, head: list[AgentMessage]) -> str:
        """Run one model call to summarize ``head``; returns its text (best-effort)."""
        prompt = head + [UserMessage(content="Summarize the conversation above as instructed.")]
        text_parts: list[str] = []
        async for event in self._model.stream(
            system_prompt=_SUMMARY_SYSTEM_PROMPT,
            messages=to_llm_messages(prompt),
            tools=None,
        ):
            if event.type == "text_delta" and event.delta:
                text_parts.append(event.delta)
            if event.is_terminal:
                final = event.final_message
                if not text_parts and final is not None:
                    text_parts.append(_text_of_message(final))
        return "".join(text_parts).strip() or "(summary unavailable)"


def _text_of_message(message: Any) -> str:
    """Concatenate the text blocks of an assistant message."""
    out: list[str] = []
    for block in getattr(message, "content", None) or []:
        btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if btype == "text":
            out.append(block.get("text", "") if isinstance(block, dict) else getattr(block, "text", ""))
    return "".join(out)
