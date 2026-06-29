"""Fitness test: keep the single tool registry and the permission policy in sync.

The built-in tools have one source of truth (``BUILTIN_TOOL_CLASSES``); each tool also owns
its own permission policy (``read_only`` / ``permission_target``). These invariants are easy
to break silently when adding a tool, so assert them here instead of relying on a linter.
"""

from __future__ import annotations

from pydantic import BaseModel

from agent.permissions import MUTATING_TOOLS, READ_ONLY_TOOLS, PermissionMode, Permissions
from agent.tools import BUILTIN_TOOL_CLASSES, TOOL_CLASSES, coding_tools
from agent.types import Tool, ToolResult


def test_registry_is_the_single_source_of_the_built_in_set():
    # TOOL_CLASSES and coding_tools() both derive from BUILTIN_TOOL_CLASSES → same names.
    registry_names = [cls.name for cls in BUILTIN_TOOL_CLASSES]
    assert list(TOOL_CLASSES) == registry_names
    assert [t.name for t in coding_tools(".")] == registry_names
    assert len(set(registry_names)) == len(registry_names)  # names are unique


def test_every_tool_declares_a_boolean_policy():
    for cls in BUILTIN_TOOL_CLASSES:
        assert isinstance(cls.read_only, bool), cls.__name__
        # permission_target must be callable and return a string for empty args.
        assert isinstance(cls.permission_target({}), str), cls.__name__


def test_name_only_fallback_agrees_with_each_tool_policy():
    # The fallback frozensets exist only for name-only decide(); a tool's own read_only flag
    # is authoritative. If they drift, this catches it.
    for cls in BUILTIN_TOOL_CLASSES:
        in_read_only = cls.name in READ_ONLY_TOOLS
        in_mutating = cls.name in MUTATING_TOOLS
        assert in_read_only is cls.read_only, cls.name
        assert in_read_only ^ in_mutating, cls.name  # classified exactly once


def test_default_mode_decision_follows_the_tool_policy():
    perms = Permissions(mode=PermissionMode.DEFAULT)
    for tool in coding_tools("."):
        decision = perms.decide(tool.name, {}, tool)
        assert decision == ("allow" if tool.read_only else "ask"), tool.name


class _NoteArgs(BaseModel):
    topic: str


class _CustomTool(Tool):
    """A custom tool the built-in name sets have never heard of — its own policy must win."""

    name = "scribble"
    description = "Record a scribble."
    parameters = _NoteArgs
    read_only = True

    @classmethod
    def permission_target(cls, args):
        return str(args.get("topic", ""))

    async def execute(self, args, *, on_update=None):  # pragma: no cover - not run
        return ToolResult(content="ok")


def test_policy_is_sourced_from_the_tool_not_the_name_sets():
    perms = Permissions(mode=PermissionMode.DEFAULT)
    tool = _CustomTool()
    # 'scribble' is in neither READ_ONLY_TOOLS nor MUTATING_TOOLS, yet read_only=True is honored.
    assert "scribble" not in READ_ONLY_TOOLS and "scribble" not in MUTATING_TOOLS
    assert perms.decide("scribble", {"topic": "x"}, tool) == "allow"
    # ...and the tool's permission_target drives glob rules (matches on `topic`, not `path`).
    denied = Permissions(deny=["scribble(secret*)"])
    assert denied.decide("scribble", {"topic": "secret-plan"}, tool) == "deny"
    assert denied.decide("scribble", {"topic": "public"}, tool) == "allow"
