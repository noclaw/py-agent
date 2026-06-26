"""Tool registry and bundles.

``coding_tools(cwd)`` returns the full built-in set (read/write/edit/bash/grep/find/ls),
and ``read_only_tools(cwd)`` the non-mutating subset. This package is the seam where
second-brain / assistant users swap the coding toolset for their own (e.g. note/recall/
memory tools) — build a list of :class:`~agent.types.Tool` instances and hand it to
``run_agent``.
"""

from __future__ import annotations

from pathlib import Path

from ..types import Tool
from .bash import BashTool
from .edit import EditTool
from .find import FindTool
from .grep import GrepTool
from .ls import LsTool
from .read import ReadTool
from .task import TaskTool
from .web import WebFetchTool, WebSearchTool
from .write import WriteTool

__all__ = [
    "Tool",
    "ReadTool",
    "WriteTool",
    "EditTool",
    "BashTool",
    "GrepTool",
    "FindTool",
    "LsTool",
    "TaskTool",
    "WebFetchTool",
    "WebSearchTool",
    "coding_tools",
    "read_only_tools",
    "with_task_tool",
    "TOOL_CLASSES",
]

#: All built-in tool classes, by name.
TOOL_CLASSES: dict[str, type[Tool]] = {
    cls.name: cls
    for cls in (ReadTool, WriteTool, EditTool, BashTool, GrepTool, FindTool, LsTool,
                WebFetchTool, WebSearchTool)
}


def coding_tools(cwd: str | Path = ".") -> list[Tool]:
    """The full built-in tool set, bound to ``cwd`` (plus the network web tools)."""
    return [
        ReadTool(cwd),
        GrepTool(cwd),
        FindTool(cwd),
        LsTool(cwd),
        BashTool(cwd),
        EditTool(cwd),
        WriteTool(cwd),
        WebFetchTool(),
        WebSearchTool(),
    ]


def read_only_tools(cwd: str | Path = ".") -> list[Tool]:
    """The non-mutating subset (read/grep/find/ls) — handy for analysis-only agents."""
    return [ReadTool(cwd), GrepTool(cwd), FindTool(cwd), LsTool(cwd)]


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
