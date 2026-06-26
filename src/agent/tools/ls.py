"""List directory contents. Port: tools/ls.ts."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult, truncate_head


class LsArgs(BaseModel):
    path: str | None = Field(default=None, description="Directory to list (default: cwd).")
    limit: int = Field(default=500, description="Maximum number of entries to return.")


class LsTool(BaseTool):
    name = "ls"
    description = (
        "List the contents of a directory, sorted alphabetically. Directories are shown "
        "with a trailing '/'. Includes dotfiles."
    )
    parameters = LsArgs
    prompt_snippet = "ls: List directory contents"
    read_only = True

    async def execute(self, args: LsArgs, *, on_update=None) -> ToolResult:
        path = self.resolve(args.path) if args.path else self.cwd
        if not path.exists():
            return ToolResult(content=f"Path not found: {args.path or '.'}", is_error=True)
        if not path.is_dir():
            return ToolResult(content=f"Not a directory: {args.path or '.'}", is_error=True)

        entries = await asyncio.to_thread(self._list, path, args.limit)
        if not entries:
            return ToolResult(content="(empty directory)")
        body, truncated = truncate_head("\n".join(entries))
        if truncated or len(entries) >= args.limit:
            body += f"\n\n[stopped at {args.limit} entries]"
        return ToolResult(content=body)

    @staticmethod
    def _list(path: Path, limit: int) -> list[str]:
        out: list[str] = []
        for entry in sorted(path.iterdir(), key=lambda p: p.name):
            out.append(entry.name + "/" if entry.is_dir() else entry.name)
            if len(out) >= limit:
                break
        return out
