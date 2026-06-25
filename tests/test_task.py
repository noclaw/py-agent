"""The `task` tool: spawns a sub-agent run and returns its final report."""

from __future__ import annotations

from pydantic import BaseModel

from agent.tools import TaskTool, coding_tools, with_task_tool
from agent.tools.task import TaskArgs
from agent.types import Tool, ToolResult
from fakes import FakeModel, text_turn, tool_turn


class EchoArgs(BaseModel):
    text: str


class EchoTool(Tool):
    name = "echo"
    description = "Echo text."
    parameters = EchoArgs

    async def execute(self, args: EchoArgs, *, on_update=None) -> ToolResult:
        return ToolResult(content=args.text)


async def test_task_returns_subagent_report():
    model = FakeModel([text_turn("Here is the report.")])
    tool = TaskTool(model=model, tools=[], cwd=".")
    result = await tool.execute(TaskArgs(description="scout", prompt="look around"))
    assert not result.is_error
    assert result.content == "Here is the report."
    # The sub-agent was prompted with our instructions.
    assert model.calls[0]["messages"][0]["content"] == "look around"


async def test_task_streams_subagent_tool_activity():
    model = FakeModel([tool_turn([("c1", "echo", {"text": "hi"})]), text_turn("done")])
    tool = TaskTool(model=model, tools=[EchoTool()], cwd=".")
    updates: list[str] = []
    result = await tool.execute(
        TaskArgs(description="work", prompt="echo hi"), on_update=updates.append
    )
    assert result.content == "done"
    assert any("echo" in u for u in updates)  # parent saw the sub-agent's tool call


async def test_task_reports_empty_run_as_error():
    model = FakeModel([text_turn("")])  # no usable text
    tool = TaskTool(model=model, tools=[], cwd=".")
    result = await tool.execute(TaskArgs(description="x", prompt="y"))
    assert result.is_error


def test_with_task_tool_appends_a_non_recursive_task_tool():
    model = FakeModel([])
    base = coding_tools(".")
    tools = with_task_tool(base, model=model, cwd=".")
    assert isinstance(tools[-1], TaskTool)
    # The sub-agent's own toolset must not contain a nested task tool (no recursion).
    child = tools[-1]._tools
    assert not any(isinstance(t, TaskTool) for t in child)
