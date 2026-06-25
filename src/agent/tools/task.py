"""The ``task`` tool — spawn a sub-agent with its own toolset and turn budget.

Port target: Claude Code's ``Task`` tool / Pi sub-agents.

A sub-agent is just a nested :func:`agent.loop.run_agent` run: the tool hands the child a
fresh history seeded with the caller's prompt, a restricted toolset, and its own ``max_turns``
budget, then returns the child's final assistant text as the tool result. This enables a
"scout → plan → implement" style of delegation without the parent's context filling up with
the child's intermediate tool churn.

The child never gets a ``task`` tool of its own (no unbounded recursion), and runs
``sequential`` so its model stream never overlaps the parent's on the shared client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..system_prompt import build_system_prompt
from ..types import AssistantDone, ToolResult, ToolStart, user_message
from .base import BaseTool

if TYPE_CHECKING:
    from ..loop import Approver
    from ..model import ModelLike
    from ..permissions import Permissions
    from ..types import Tool

#: Sub-agents get a tighter turn budget than the top-level loop.
DEFAULT_SUBAGENT_MAX_TURNS = 15

_SUBAGENT_PERSONA = (
    "You are a sub-agent launched to handle one focused task on behalf of a coding agent. "
    "Work autonomously: use your tools to investigate and act, then finish with a single "
    "clear report of what you found or did. Your final message is the whole result the "
    "calling agent receives, so make it self-contained — do not ask follow-up questions."
)


class TaskArgs(BaseModel):
    description: str = Field(description="A short (3-5 word) description of the task.")
    prompt: str = Field(description="The full instructions for the sub-agent to carry out.")


class TaskTool(BaseTool):
    name = "task"
    description = (
        "Delegate a self-contained sub-task to a sub-agent with its own tools and budget. "
        "Use it to scout/research or carry out focused work without cluttering your own "
        "context. The sub-agent runs autonomously and returns a single final report; it "
        "cannot ask you questions, so give it everything it needs in `prompt`."
    )
    parameters = TaskArgs
    prompt_snippet = "task: Delegate a focused sub-task to a sub-agent"
    execution_mode = "sequential"

    def __init__(
        self,
        *,
        model: "ModelLike",
        tools: list["Tool"],
        cwd: str = ".",
        system_prompt: str | None = None,
        max_turns: int = DEFAULT_SUBAGENT_MAX_TURNS,
        permissions: "Permissions | None" = None,
        approver: "Approver | None" = None,
    ) -> None:
        super().__init__(cwd)
        self._model = model
        self._tools = tools
        self._max_turns = max_turns
        self._permissions = permissions
        self._approver = approver
        self._system_prompt = system_prompt or build_system_prompt(
            tools, cwd, custom=_SUBAGENT_PERSONA
        )

    async def execute(self, args: TaskArgs, *, on_update=None) -> ToolResult:
        # Local import avoids a tools → loop → tools import cycle at module load.
        from ..loop import run_agent

        history = [user_message(args.prompt)]
        final_text = ""
        async for event in run_agent(
            self._model,
            self._tools,
            history,
            system_prompt=self._system_prompt,
            permissions=self._permissions,
            approver=self._approver,
            max_turns=self._max_turns,
        ):
            if isinstance(event, ToolStart) and on_update is not None:
                on_update(f"[{args.description}] {event.tool_name}")
            elif isinstance(event, AssistantDone):
                text = _assistant_text(event.message)
                if text:
                    final_text = text  # keep the latest assistant text as the report
        if not final_text:
            return ToolResult(content="Sub-agent finished without producing a report.", is_error=True)
        return ToolResult(content=final_text)


def _assistant_text(message) -> str:
    out: list[str] = []
    for block in getattr(message, "content", None) or []:
        btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if btype == "text":
            out.append(block.get("text", "") if isinstance(block, dict) else getattr(block, "text", ""))
    return "".join(out).strip()
