"""Edit a file via exact-match text replacements. Port: tools/edit.ts."""

from __future__ import annotations

import asyncio
import difflib

from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult


class EditOp(BaseModel):
    old_text: str = Field(description="Exact text to find. Must match a unique region.")
    new_text: str = Field(description="Replacement text.")


class EditArgs(BaseModel):
    path: str = Field(description="Path to the file to edit.")
    edits: list[EditOp] = Field(description="One or more exact-match replacements to apply.")


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Edit a file with exact text replacements. Each edit's old_text must match a "
        "unique region of the current file. Include enough surrounding context to make "
        "each match unique."
    )
    parameters = EditArgs
    prompt_snippet = "edit: Replace exact text in a file"
    prompt_guidelines = ("Prefer edit over write when changing part of an existing file.",)

    async def execute(self, args: EditArgs, *, on_update=None) -> ToolResult:
        path = self.resolve(args.path)
        if not path.exists():
            return ToolResult(content=f"File not found: {args.path}", is_error=True)
        if path.is_dir():
            return ToolResult(content=f"Not a file: {args.path}", is_error=True)
        if not args.edits:
            return ToolResult(content="No edits provided.", is_error=True)

        try:
            original = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except OSError as exc:
            return ToolResult(content=f"Could not read {args.path}: {exc}", is_error=True)

        updated = original
        for i, op in enumerate(args.edits, 1):
            count = updated.count(op.old_text)
            if count == 0:
                return ToolResult(
                    content=f"Edit {i}: old_text not found in {args.path}.", is_error=True
                )
            if count > 1:
                return ToolResult(
                    content=(
                        f"Edit {i}: old_text matches {count} places in {args.path}; "
                        "add surrounding context to make it unique."
                    ),
                    is_error=True,
                )
            updated = updated.replace(op.old_text, op.new_text, 1)

        if updated == original:
            return ToolResult(content="No changes (edits produced identical content).", is_error=True)

        try:
            await asyncio.to_thread(path.write_text, updated, encoding="utf-8")
        except OSError as exc:
            return ToolResult(content=f"Could not write {args.path}: {exc}", is_error=True)

        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=f"a/{args.path}",
                tofile=f"b/{args.path}",
            )
        )
        return ToolResult(
            content=f"Applied {len(args.edits)} edit(s) to {args.path}.\n\n{diff}",
            details={"path": str(path), "diff": diff},
        )
