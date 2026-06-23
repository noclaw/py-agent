"""Write a file (create dirs; new files or full rewrites). Port: tools/write.ts."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult


class WriteArgs(BaseModel):
    path: str = Field(description="Path to write, relative to the working directory.")
    content: str = Field(description="The full file contents to write.")


class WriteTool(BaseTool):
    name = "write"
    description = (
        "Write content to a file, creating it (and any parent directories) if needed and "
        "overwriting it if it exists."
    )
    parameters = WriteArgs
    prompt_snippet = "write: Create or overwrite a file"
    prompt_guidelines = ("Use write only for new files or complete rewrites; use edit to change part of a file.",)

    async def execute(self, args: WriteArgs, *, on_update=None) -> ToolResult:
        path = self.resolve(args.path)
        if path.is_dir():
            return ToolResult(content=f"Cannot write: {args.path} is a directory", is_error=True)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args.content, encoding="utf-8")

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            return ToolResult(content=f"Could not write {args.path}: {exc}", is_error=True)

        lines = args.content.count("\n") + 1 if args.content else 0
        return ToolResult(
            content=f"Wrote {len(args.content)} bytes ({lines} lines) to {args.path}",
            details={"path": str(path), "bytes": len(args.content)},
        )
