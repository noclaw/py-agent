"""A todo / planning tool (Claude Code's ``TodoWrite`` shape) — PLAN feature #3.

Unlike every other built-in, this tool mutates *shared run state* rather than the
filesystem: it holds the current plan as a list on the instance, and each call **replaces**
the whole list (write semantics — the model sends the full, updated set every time). The
renderer special-cases it to draw a live checklist; the model gets the same list back as
text so it can track a multi-step task.

It's read-only with respect to the workspace, so it's auto-allowed (no gating) — the same
treatment Claude Code gives ``TodoWrite``.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from ..types import Tool, ToolResult

__all__ = ["TodoStatus", "TodoItem", "TodoWriteArgs", "TodoWriteTool", "render_todos", "STATUS_MARK"]


class TodoStatus(str, Enum):
    """A todo item's state."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


#: ASCII marker shown for each status in the text the model sees.
STATUS_MARK = {
    TodoStatus.PENDING: "[ ]",
    TodoStatus.IN_PROGRESS: "[~]",
    TodoStatus.COMPLETED: "[x]",
}


class TodoItem(BaseModel):
    content: str = Field(description="What the step is, e.g. 'Add the parser tests'.")
    status: TodoStatus = Field(default=TodoStatus.PENDING, description="pending | in_progress | completed.")


class TodoWriteArgs(BaseModel):
    todos: list[TodoItem] = Field(
        description="The full todo list, in order. Sending this replaces the previous list entirely."
    )


def render_todos(todos: list[TodoItem]) -> str:
    """The checklist as plain text (what the model sees in the tool result)."""
    if not todos:
        return "(todo list cleared)"
    done = sum(1 for t in todos if t.status is TodoStatus.COMPLETED)
    lines = [f"Todos ({done}/{len(todos)} done):"]
    lines += [f"{STATUS_MARK[t.status]} {t.content}" for t in todos]
    return "\n".join(lines)


class TodoWriteTool(Tool):
    name = "todo_write"
    description = (
        "Record or update a structured todo list for the current task. Send the full list "
        "each time (it replaces the previous one). Mark exactly one item in_progress while "
        "you work on it, and completed as soon as it's done."
    )
    parameters = TodoWriteArgs
    prompt_snippet = "todo_write: Track a multi-step plan as a checklist"
    prompt_guidelines = (
        "For multi-step tasks, use todo_write to plan and keep the list updated as you go "
        "(one item in_progress at a time); skip it for trivial one-step tasks.",
    )
    #: Mutates run state, not the workspace → auto-allowed like the read-only tools.
    read_only = True

    def __init__(self, cwd: str = ".") -> None:  # accepts/ignores cwd to fit the cls(cwd) registry
        self.todos: list[TodoItem] = []

    async def execute(self, args: TodoWriteArgs, *, on_update=None) -> ToolResult:
        self.todos = list(args.todos)
        return ToolResult(content=render_todos(self.todos), details={"todos": self.todos})
