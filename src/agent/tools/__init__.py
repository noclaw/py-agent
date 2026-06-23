"""Tool registry and bundles.

Port target: ``packages/coding-agent/src/core/tools/index.ts``.

``coding_tools(cwd)`` returns the default coding set (read/write/edit/bash). This package
is the seam where second-brain / assistant users swap the coding toolset for their own
(e.g. note/recall/memory tools) — build a list of :class:`~agent.types.Tool`
instances and hand it to ``run_agent``.

(grep/find/ls are planned follow-ups to the default set.)
"""

from __future__ import annotations

from pathlib import Path

from ..types import Tool
from .bash import BashTool
from .edit import EditTool
from .read import ReadTool
from .write import WriteTool

__all__ = [
    "Tool",
    "ReadTool",
    "WriteTool",
    "EditTool",
    "BashTool",
    "coding_tools",
    "TOOL_CLASSES",
]

#: All built-in tool classes, by name.
TOOL_CLASSES: dict[str, type[Tool]] = {
    ReadTool.name: ReadTool,
    WriteTool.name: WriteTool,
    EditTool.name: EditTool,
    BashTool.name: BashTool,
}


def coding_tools(cwd: str | Path = ".") -> list[Tool]:
    """The default coding tool set, bound to ``cwd`` (matches Pi's coding bundle order)."""
    return [ReadTool(cwd), BashTool(cwd), EditTool(cwd), WriteTool(cwd)]
