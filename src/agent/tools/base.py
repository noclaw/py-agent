"""Shared tool plumbing.

The :class:`~agent.types.Tool` protocol and :class:`~agent.types.ToolResult`
live in :mod:`agent.types` (re-exported here). This module adds the helpers the
concrete tools share: a working-directory base, path resolution, and output truncation.
"""

from __future__ import annotations

from pathlib import Path

from ..types import Tool, ToolResult

__all__ = [
    "Tool",
    "ToolResult",
    "DEFAULT_MAX_LINES",
    "DEFAULT_MAX_BYTES",
    "truncate_head",
    "truncate_tail",
    "BaseTool",
]

#: Output budgets (whichever is hit first). Roughly mirrors common tool defaults.
DEFAULT_MAX_LINES = 1000
DEFAULT_MAX_BYTES = 100_000


def _truncate(text: str, max_lines: int, max_bytes: int, *, tail: bool) -> tuple[str, bool]:
    truncated = False
    lines = text.split("\n")
    if len(lines) > max_lines:
        truncated = True
        lines = lines[-max_lines:] if tail else lines[:max_lines]
        text = "\n".join(lines)
    data = text.encode("utf-8")
    if len(data) > max_bytes:
        truncated = True
        data = data[-max_bytes:] if tail else data[:max_bytes]
        text = data.decode("utf-8", errors="ignore")
    return text, truncated


def truncate_head(
    text: str, *, max_lines: int = DEFAULT_MAX_LINES, max_bytes: int = DEFAULT_MAX_BYTES
) -> tuple[str, bool]:
    """Keep the first lines/bytes (for file reads). Returns (text, was_truncated)."""
    return _truncate(text, max_lines, max_bytes, tail=False)


def truncate_tail(
    text: str, *, max_lines: int = DEFAULT_MAX_LINES, max_bytes: int = DEFAULT_MAX_BYTES
) -> tuple[str, bool]:
    """Keep the last lines/bytes (for command output). Returns (text, was_truncated)."""
    return _truncate(text, max_lines, max_bytes, tail=True)


class BaseTool(Tool):
    """A tool bound to a working directory, with path resolution.

    Concrete tools subclass this, set the class attributes, and implement ``execute``.
    """

    def __init__(self, cwd: str | Path = ".") -> None:
        self.cwd = Path(cwd)

    def resolve(self, path: str) -> Path:
        """Resolve ``path`` against the working directory (absolute paths unchanged)."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else (self.cwd / p)
