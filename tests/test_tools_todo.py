"""The todo / planning tool (PLAN #3) — mutates shared run state, not the filesystem."""

from __future__ import annotations

from agent.permissions import PermissionMode, Permissions
from agent.tools import coding_tools
from agent.tools.todo import (
    TodoItem,
    TodoStatus,
    TodoWriteArgs,
    TodoWriteTool,
    render_todos,
)


def _items(*pairs) -> list[TodoItem]:
    return [TodoItem(content=c, status=s) for c, s in pairs]


async def test_write_replaces_list_and_renders():
    tool = TodoWriteTool()
    args = TodoWriteArgs(
        todos=_items(
            ("write the parser", TodoStatus.COMPLETED),
            ("wire it up", TodoStatus.IN_PROGRESS),
            ("add tests", TodoStatus.PENDING),
        )
    )
    result = await tool.execute(args)
    assert not result.is_error
    assert "1/3 done" in result.content
    assert "[x] write the parser" in result.content
    assert "[~] wire it up" in result.content
    assert "[ ] add tests" in result.content
    # details carry the structured list for the renderer
    assert [t.content for t in result.details["todos"]] == ["write the parser", "wire it up", "add tests"]


async def test_write_is_full_replacement():
    tool = TodoWriteTool()
    await tool.execute(TodoWriteArgs(todos=_items(("a", TodoStatus.PENDING), ("b", TodoStatus.PENDING))))
    result = await tool.execute(TodoWriteArgs(todos=_items(("c", TodoStatus.COMPLETED))))
    assert [t.content for t in tool.todos] == ["c"]
    assert "1/1 done" in result.content
    assert "a" not in result.content and "b" not in result.content


async def test_empty_list_clears():
    tool = TodoWriteTool()
    await tool.execute(TodoWriteArgs(todos=_items(("a", TodoStatus.PENDING))))
    result = await tool.execute(TodoWriteArgs(todos=[]))
    assert tool.todos == []
    assert "cleared" in result.content


def test_render_todos_helper():
    assert render_todos([]) == "(todo list cleared)"
    assert render_todos(_items(("x", TodoStatus.COMPLETED))) == "Todos (1/1 done):\n[x] x"


def test_default_status_is_pending():
    assert TodoItem(content="x").status is TodoStatus.PENDING


def test_todo_is_auto_allowed_and_in_default_set():
    assert TodoWriteTool.read_only is True
    perms = Permissions(mode=PermissionMode.DEFAULT)
    tool = TodoWriteTool()
    assert perms.decide("todo_write", {"todos": []}, tool) == "allow"
    assert "todo_write" in [t.name for t in coding_tools(".")]
