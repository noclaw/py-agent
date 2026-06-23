"""Tool registry and bundles.

Port target: ``packages/coding-agent/src/core/tools/index.ts``.

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
    "coding_tools",
    "read_only_tools",
    "TOOL_CLASSES",
]

#: All built-in tool classes, by name.
TOOL_CLASSES: dict[str, type[Tool]] = {
    cls.name: cls
    for cls in (ReadTool, WriteTool, EditTool, BashTool, GrepTool, FindTool, LsTool)
}


def coding_tools(cwd: str | Path = ".") -> list[Tool]:
    """The full built-in tool set, bound to ``cwd``."""
    return [
        ReadTool(cwd),
        GrepTool(cwd),
        FindTool(cwd),
        LsTool(cwd),
        BashTool(cwd),
        EditTool(cwd),
        WriteTool(cwd),
    ]


def read_only_tools(cwd: str | Path = ".") -> list[Tool]:
    """The non-mutating subset (read/grep/find/ls) — handy for analysis-only agents."""
    return [ReadTool(cwd), GrepTool(cwd), FindTool(cwd), LsTool(cwd)]
