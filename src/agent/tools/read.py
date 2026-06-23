"""Read a file's contents (with offset/limit + truncation). Port: tools/read.ts."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult, truncate_head


class ReadArgs(BaseModel):
    path: str = Field(description="Path to the file, relative to the working directory.")
    offset: int | None = Field(default=None, description="1-indexed line to start at.")
    limit: int | None = Field(default=None, description="Maximum number of lines to read.")


class ReadTool(BaseTool):
    name = "read"
    description = (
        "Read the contents of a text file. Output is truncated if very large; use "
        "offset (1-indexed start line) and limit to page through big files."
    )
    parameters = ReadArgs
    prompt_snippet = "read: Read a file's contents"

    async def execute(self, args: ReadArgs, *, on_update=None) -> ToolResult:
        path = self.resolve(args.path)
        if not path.exists():
            return ToolResult(content=f"File not found: {args.path}", is_error=True)
        if path.is_dir():
            return ToolResult(content=f"Not a file (it's a directory): {args.path}", is_error=True)

        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(content=f"Could not read {args.path}: {exc}", is_error=True)

        lines = text.split("\n")
        if args.offset or args.limit:
            start = max((args.offset - 1) if args.offset else 0, 0)
            end = (start + args.limit) if args.limit else None
            lines = lines[start:end]
        body = "\n".join(lines)

        body, truncated = truncate_head(body)
        if truncated:
            body += "\n\n[truncated — use offset/limit to read more]"
        return ToolResult(content=body)
