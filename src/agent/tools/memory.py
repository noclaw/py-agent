"""Memory / second-brain tools over a local markdown store.

The repurposing showcase from ``docs/building-your-own-agent.md`` (PLAN feature #1): a tiny
persistent memory the agent can write to and read back across sessions. Three tools share one
plain-markdown file (one timestamped bullet per note), so the store is human-readable and
editable by hand:

- ``note`` — append a note (mutating → gated like ``write``/``edit``).
- ``recall`` — read back the most recent notes (read-only → auto-allowed).
- ``search_memory`` — find notes matching a query (read-only → auto-allowed).

The store defaults to ``~/.pya/memory.md`` (a per-user second brain that persists across
projects, alongside ``settings.toml``); override it with the ``PYA_MEMORY_FILE`` env var or
the ``store=`` constructor argument (the tests use the latter). These tools accept and ignore
``cwd`` so they slot into the same ``cls(cwd)`` registry as the file tools.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from ..types import Tool, ToolResult
from .base import truncate_tail

__all__ = ["NoteTool", "RecallTool", "SearchMemoryTool", "default_store", "MEMORY_PATH"]

#: Default per-user memory store (next to ``~/.pya/settings.toml``).
MEMORY_PATH = Path.home() / ".pya" / "memory.md"


def default_store() -> Path:
    """The memory file: ``PYA_MEMORY_FILE`` if set, else :data:`MEMORY_PATH`."""
    env = os.environ.get("PYA_MEMORY_FILE")
    return Path(env).expanduser() if env else MEMORY_PATH


class _MemoryTool(Tool):
    """Shared base: a tool bound to one markdown memory file.

    ``cwd`` is accepted and ignored (the store is global, not workspace-relative) so these
    construct as ``cls(cwd)`` like every other built-in tool.
    """

    def __init__(self, cwd: str | Path = ".", *, store: str | Path | None = None) -> None:
        self.store = Path(store).expanduser() if store is not None else default_store()

    def _read_notes(self) -> list[str]:
        """The store's note lines (the ``- `` bullets), oldest first; [] if no store yet."""
        if not self.store.exists():
            return []
        lines = self.store.read_text(encoding="utf-8").splitlines()
        return [ln for ln in lines if ln.startswith("- ")]


class NoteArgs(BaseModel):
    text: str = Field(description="The note to remember (a single fact or reminder).")


class NoteTool(_MemoryTool):
    name = "note"
    description = (
        "Save a note to long-term memory. Notes persist across sessions in a local markdown "
        "file; read them back with recall or search_memory."
    )
    parameters = NoteArgs
    prompt_snippet = "note: Save a note to long-term memory"
    prompt_guidelines = ("Use note to remember durable facts/preferences the user shares, not transient task state.",)

    @classmethod
    def permission_target(cls, args: dict) -> str:
        # No path; gate on the note text so a rule like ``note(*secret*)`` can match.
        return str(args.get("text", ""))

    async def execute(self, args: NoteArgs, *, on_update=None) -> ToolResult:
        text = args.text.strip()
        if not text:
            return ToolResult(content="Nothing to save: note text is empty.", is_error=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- {stamp} — {text}\n"

        def _append() -> None:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            with self.store.open("a", encoding="utf-8") as fh:
                fh.write(entry)

        try:
            await asyncio.to_thread(_append)
        except OSError as exc:
            return ToolResult(content=f"Could not save note: {exc}", is_error=True)
        return ToolResult(content=f"Saved note: {text}", details={"store": str(self.store)})


class RecallArgs(BaseModel):
    limit: int = Field(default=20, description="How many of the most recent notes to return.")


class RecallTool(_MemoryTool):
    name = "recall"
    description = (
        "Recall the most recent notes from long-term memory, newest last. Use search_memory "
        "to find notes by keyword."
    )
    parameters = RecallArgs
    prompt_snippet = "recall: Read recent notes from long-term memory"
    read_only = True

    async def execute(self, args: RecallArgs, *, on_update=None) -> ToolResult:
        notes = self._read_notes()
        if not notes:
            return ToolResult(content="(no notes yet)")
        limit = max(args.limit, 1)
        recent = notes[-limit:]
        body, _ = truncate_tail("\n".join(recent))
        if len(notes) > len(recent):
            body = f"[showing the most recent {len(recent)} of {len(notes)} notes]\n{body}"
        return ToolResult(content=body)


class SearchMemoryArgs(BaseModel):
    query: str = Field(description="Text or regular expression to search notes for.")
    ignore_case: bool = Field(default=True, description="Case-insensitive match (default: true).")


class SearchMemoryTool(_MemoryTool):
    name = "search_memory"
    description = (
        "Search long-term memory for notes matching a query (substring or regular "
        "expression). Returns the matching notes."
    )
    parameters = SearchMemoryArgs
    prompt_snippet = "search_memory: Search long-term memory for notes"
    read_only = True

    async def execute(self, args: SearchMemoryArgs, *, on_update=None) -> ToolResult:
        try:
            regex = re.compile(args.query, re.IGNORECASE if args.ignore_case else 0)
        except re.error as exc:
            return ToolResult(content=f"Invalid query: {exc}", is_error=True)
        hits = [ln for ln in self._read_notes() if regex.search(ln)]
        if not hits:
            return ToolResult(content="(no matching notes)")
        body, _ = truncate_tail("\n".join(hits))
        return ToolResult(content=body)
