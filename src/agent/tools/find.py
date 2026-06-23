"""Find files by glob pattern. Port: tools/find.ts.

Pure-Python via ``pathlib`` globbing; skips common noise directories.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult, truncate_head
from .grep import SKIP_DIRS


class FindArgs(BaseModel):
    pattern: str = Field(description="Glob pattern, e.g. '*.py' or '**/test_*.py'.")
    path: str | None = Field(default=None, description="Directory to search in (default: cwd).")
    limit: int = Field(default=1000, description="Maximum number of paths to return.")


class FindTool(BaseTool):
    name = "find"
    description = (
        "Find files by glob pattern (use ** to recurse). Returns paths relative to the "
        "search directory. Skips VCS/build directories."
    )
    parameters = FindArgs
    prompt_snippet = "find: Find files by glob pattern"

    async def execute(self, args: FindArgs, *, on_update=None) -> ToolResult:
        base = self.resolve(args.path) if args.path else self.cwd
        if not base.is_dir():
            return ToolResult(content=f"Not a directory: {args.path or '.'}", is_error=True)

        paths = await asyncio.to_thread(self._find, base, args.pattern, args.limit)
        if not paths:
            return ToolResult(content="(no files matched)")
        body, truncated = truncate_head("\n".join(paths))
        if truncated or len(paths) >= args.limit:
            body += f"\n\n[stopped at {args.limit} results]"
        return ToolResult(content=body)

    def _find(self, base: Path, pattern: str, limit: int) -> list[str]:
        out: list[str] = []
        for path in sorted(base.glob(pattern)):
            if path.is_dir():
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(base).parts):
                continue
            out.append(str(path.relative_to(base)))
            if len(out) >= limit:
                break
        return out
