"""Terminal rendering of the loop's event stream.

A small, readable renderer built on ``rich``: it streams assistant text (and optionally
thinking), announces tool calls and their results, and prints a usage summary when the run
ends. Port reference: ``packages/coding-agent/src/modes/interactive/``.

The renderer is deliberately stateless except for a little bookkeeping (whether we're
mid-line, and accumulated token usage) so it's easy to follow and to test.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console

from .types import (
    AgentEnd,
    AgentEvent,
    AssistantDelta,
    AssistantDone,
    ToolEnd,
    ToolStart,
)


def _summarize_args(args: dict[str, Any], *, limit: int = 80) -> str:
    """Render tool arguments as a short single line."""
    try:
        text = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(args)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _first_line(text: str, *, limit: int = 120) -> str:
    line = text.strip().split("\n", 1)[0]
    return line if len(line) <= limit else line[: limit - 1] + "…"


class Renderer:
    """Renders :class:`AgentEvent`s to a console.

    Args:
        console: a ``rich`` Console (defaults to a new one).
        show_thinking: stream the model's reasoning (dimmed) if present.
    """

    def __init__(self, console: Console | None = None, *, show_thinking: bool = True) -> None:
        self.console = console or Console()
        self.show_thinking = show_thinking
        self._mid_line = False  # are we in the middle of a streamed line?
        self._tokens = 0

    # -- helpers ----------------------------------------------------------

    def _newline_if_needed(self) -> None:
        if self._mid_line:
            self.console.print()
            self._mid_line = False

    def _write(self, text: str, *, style: str | None = None) -> None:
        self.console.print(text, end="", style=style, markup=False, highlight=False, soft_wrap=True)
        self._mid_line = not text.endswith("\n")

    # -- event handling ---------------------------------------------------

    def handle(self, event: AgentEvent) -> None:
        if isinstance(event, AssistantDelta):
            self._on_delta(event)
        elif isinstance(event, AssistantDone):
            self._newline_if_needed()
            self._accumulate_usage(event.message)
        elif isinstance(event, ToolStart):
            self._newline_if_needed()
            self.console.print(
                f"[dim]›[/dim] [cyan]{event.tool_name}[/cyan] [dim]{_summarize_args(event.args)}[/dim]"
            )
        elif isinstance(event, ToolEnd):
            result = event.result
            if result.is_error:
                self.console.print(f"  [red]✗ {_first_line(result.content)}[/red]")
            else:
                self.console.print(f"  [green]✓[/green] [dim]{_first_line(result.content)}[/dim]")
        elif isinstance(event, AgentEnd):
            self._on_end(event)

    def _on_delta(self, event: AssistantDelta) -> None:
        ev = event.event
        if ev.type == "text_delta" and ev.delta:
            self._write(ev.delta)
        elif ev.type == "thinking_delta" and ev.delta and self.show_thinking:
            self._write(ev.delta, style="dim italic")

    def _accumulate_usage(self, message: Any) -> None:
        usage = getattr(message, "usage", None)
        if isinstance(usage, dict):
            self._tokens += int(usage.get("totalTokens") or 0)

    def _on_end(self, event: AgentEnd) -> None:
        self._newline_if_needed()
        if event.reason == "completed":
            suffix = f" [dim]({self._tokens} tokens)[/dim]" if self._tokens else ""
            self.console.print(f"[dim]— done{suffix}[/dim]")
        elif event.reason == "aborted":
            self.console.print("[yellow]— aborted[/yellow]")
        else:
            self.console.print(f"[red]— ended: {event.reason}[/red]")

    def aborted(self) -> None:
        """Called when a turn is cancelled (Ctrl-C) before it emits AgentEnd."""
        self._newline_if_needed()
        self.console.print("[yellow]— interrupted[/yellow]")
