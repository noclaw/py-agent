"""Tool registry and bundles.

``coding_tools(cwd)`` returns the full built-in set (read/write/edit/bash/grep/find/ls plus
the web and memory tools), ``read_only_tools(cwd)`` the non-mutating subset, and
``memory_tools()`` just the note/recall/search_memory second-brain tools. This package is the
seam where second-brain / assistant users swap the coding toolset for their own — build a list
of :class:`~agent.types.Tool` instances and hand it to ``run_agent``.
"""

from __future__ import annotations

from pathlib import Path

from ..types import Tool
from .bash import BashTool
from .edit import EditTool
from .find import FindTool
from .grep import GrepTool
from .ls import LsTool
from .memory import NoteTool, RecallTool, SearchMemoryTool
from .read import ReadTool
from .task import TaskTool
from .web import WebFetchTool, WebSearchTool
from .write import WriteTool

#: The single ordered source of truth for the built-in tools. Everything below
#: (``coding_tools``, ``TOOL_CLASSES``, and the per-class ``__all__`` entries) derives from
#: it, so adding a tool means appending one class here. The order is the presentation order
#: (read-only first, then mutating, then network) used by ``coding_tools``. Every class must
#: construct as ``cls(cwd)`` — the web tools accept and ignore ``cwd`` for this reason.
BUILTIN_TOOL_CLASSES: tuple[type[Tool], ...] = (
    ReadTool,
    GrepTool,
    FindTool,
    LsTool,
    BashTool,
    EditTool,
    WriteTool,
    WebFetchTool,
    WebSearchTool,
    RecallTool,
    SearchMemoryTool,
    NoteTool,
)

#: All built-in tool classes, by name (derived from :data:`BUILTIN_TOOL_CLASSES`).
TOOL_CLASSES: dict[str, type[Tool]] = {cls.name: cls for cls in BUILTIN_TOOL_CLASSES}

__all__ = [
    "Tool",
    *(cls.__name__ for cls in BUILTIN_TOOL_CLASSES),
    "TaskTool",
    "coding_tools",
    "read_only_tools",
    "memory_tools",
    "with_task_tool",
    "BUILTIN_TOOL_CLASSES",
    "TOOL_CLASSES",
]


def coding_tools(cwd: str | Path = ".") -> list[Tool]:
    """The full built-in tool set, bound to ``cwd`` (plus the network web tools)."""
    return [cls(cwd) for cls in BUILTIN_TOOL_CLASSES]


def read_only_tools(cwd: str | Path = ".") -> list[Tool]:
    """The non-mutating subset (read/grep/find/ls) — handy for analysis-only agents."""
    return [ReadTool(cwd), GrepTool(cwd), FindTool(cwd), LsTool(cwd)]


def memory_tools(store: str | Path | None = None) -> list[Tool]:
    """Just the second-brain tools (note/recall/search_memory) over one markdown store.

    The showcase from ``docs/building-your-own-agent.md``: hand this to ``run_agent`` (with an
    assistant persona) to repurpose the loop as a note-taking second brain. ``store`` overrides
    the default ``~/.pya/memory.md``.
    """
    return [NoteTool(store=store), RecallTool(store=store), SearchMemoryTool(store=store)]


def with_task_tool(
    base: list[Tool],
    *,
    model,
    cwd: str | Path = ".",
    subagent_tools: list[Tool] | None = None,
    permissions=None,
    approver=None,
) -> list[Tool]:
    """Return ``base`` plus a :class:`TaskTool` that spawns sub-agents.

    The sub-agent's toolset defaults to a fresh ``coding_tools(cwd)`` (without a nested task
    tool, so delegation can't recurse). Pass ``permissions``/``approver`` to keep the
    sub-agent's mutating calls gated the same way as the parent's.
    """
    child_tools = subagent_tools if subagent_tools is not None else coding_tools(cwd)
    task = TaskTool(
        model=model,
        tools=child_tools,
        cwd=str(cwd),
        permissions=permissions,
        approver=approver,
    )
    return [*base, task]
