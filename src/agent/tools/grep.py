"""Search file contents with a regular expression. Port: tools/grep.ts.

Pure-Python (no ripgrep dependency) so the example stays self-contained: it walks the
tree, skips common noise dirs and binary files, and reports matching lines.
"""

from __future__ import annotations

import asyncio
import re
from fnmatch import fnmatch
from pathlib import Path

from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult, truncate_head

#: Directories never worth searching.
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", "dist", "build", ".pytest_cache"}


class GrepArgs(BaseModel):
    pattern: str = Field(description="Regular expression to search for.")
    path: str | None = Field(default=None, description="File or directory to search (default: cwd).")
    glob: str | None = Field(default=None, description="Only search files matching this glob, e.g. '*.py'.")
    ignore_case: bool = Field(default=False, description="Case-insensitive match.")
    limit: int = Field(default=100, description="Maximum number of matching lines to return.")


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Search file contents for a regular expression. Returns matching lines as "
        "'path:line: text'. Skips VCS/build directories and binary files."
    )
    parameters = GrepArgs
    prompt_snippet = "grep: Search file contents with a regex"
    read_only = True

    async def execute(self, args: GrepArgs, *, on_update=None) -> ToolResult:
        try:
            regex = re.compile(args.pattern, re.IGNORECASE if args.ignore_case else 0)
        except re.error as exc:
            return ToolResult(content=f"Invalid regex: {exc}", is_error=True)

        base = self.resolve(args.path) if args.path else self.cwd
        if not base.exists():
            return ToolResult(content=f"Path not found: {args.path}", is_error=True)

        matches = await asyncio.to_thread(self._search, base, regex, args.glob, args.limit)
        if not matches:
            return ToolResult(content="(no matches)")
        body, truncated = truncate_head("\n".join(matches))
        if truncated or len(matches) >= args.limit:
            body += f"\n\n[stopped at {args.limit} matches]"
        return ToolResult(content=body)

    def _search(self, base: Path, regex: re.Pattern[str], glob: str | None, limit: int) -> list[str]:
        files = [base] if base.is_file() else self._walk(base, glob)
        out: list[str] = []
        for file in files:
            try:
                with file.open("r", encoding="utf-8", errors="strict") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if regex.search(line):
                            rel = self._display(file)
                            out.append(f"{rel}:{lineno}: {line.rstrip()}")
                            if len(out) >= limit:
                                return out
            except (OSError, UnicodeDecodeError):
                continue  # unreadable or binary file
        return out

    def _walk(self, base: Path, glob: str | None):
        for path in sorted(base.rglob("*")):
            if path.is_dir():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if glob and not fnmatch(path.name, glob):
                continue
            yield path

    def _display(self, file: Path) -> str:
        try:
            return str(file.relative_to(self.cwd))
        except ValueError:
            return str(file)
