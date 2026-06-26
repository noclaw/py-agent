"""Permissions — decide whether a tool call may run, modeled on Claude Code.

A tool call is resolved to one of ``"allow"`` / ``"deny"`` / ``"ask"`` from:

1. **deny rules** (highest priority),
2. the **mode** (``bypass`` allows everything),
3. **allow rules**,
4. read-only tools (always allowed),
5. the mode's default for mutating tools.

Rules are strings like Claude Code's: a bare tool name (``"read"``, ``"bash"``) or a
name with a glob target — ``"bash(git *)"`` matches bash commands, ``"write(src/*)"``
matches by path. When the user approves a call "always", a matching allow rule is added
for the rest of the session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .types import Tool

__all__ = ["PermissionMode", "Decision", "Permissions", "READ_ONLY_TOOLS", "MUTATING_TOOLS"]


class PermissionMode(str, Enum):
    """How unmatched mutating tool calls are treated (Claude Code's modes)."""

    DEFAULT = "default"  # ask before mutating tools
    ACCEPT_EDITS = "acceptEdits"  # auto-allow write/edit; still ask for bash
    PLAN = "plan"  # deny all mutations (read-only exploration)
    BYPASS = "bypass"  # allow everything (a.k.a. "dangerously skip permissions")


#: Name-only fallback for the built-in read-only tools — used when :meth:`Permissions.decide`
#: is called without a tool object (e.g. in tests). At runtime the loop passes the tool and its
#: own ``read_only``/``permission_target`` policy wins, so a tool's gating lives in its own slice
#: (see :class:`agent.types.Tool`). The consistency test keeps this set in sync with the tools.
#: (The web tools do make outbound network requests; a ``deny`` rule can still block them.)
READ_ONLY_TOOLS = frozenset({"read", "grep", "find", "ls", "web_fetch", "web_search"})
#: Name-only fallback for the built-in tools that change the world → gated by mode/rules/approval.
MUTATING_TOOLS = frozenset({"write", "edit", "bash"})

# Decision values returned by :meth:`Permissions.decide`.
Decision = str  # "allow" | "deny" | "ask"


@dataclass
class Permissions:
    """Decides allow/deny/ask for tool calls; can learn session allow-rules."""

    mode: PermissionMode = PermissionMode.DEFAULT
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    read_only: frozenset[str] = READ_ONLY_TOOLS

    def decide(
        self, tool_name: str, args: dict[str, Any], tool: type[Tool] | Tool | None = None
    ) -> Decision:
        """Resolve a call to allow/deny/ask.

        When ``tool`` is supplied (the loop always passes it), the tool's own
        ``read_only``/``permission_target`` policy is authoritative. Without it, fall back to
        the built-in :data:`READ_ONLY_TOOLS` set and the name-based target map below.
        """
        read_only = tool.read_only if tool is not None else tool_name in self.read_only
        if self._matches_any(self.deny, tool_name, args, tool):
            return "deny"
        if self.mode is PermissionMode.BYPASS:
            return "allow"
        if self._matches_any(self.allow, tool_name, args, tool):
            return "allow"
        if read_only:
            return "allow"
        if self.mode is PermissionMode.PLAN:
            return "deny"
        if self.mode is PermissionMode.ACCEPT_EDITS and tool_name in ("write", "edit"):
            return "allow"
        return "ask"

    def allow_always(self, tool_name: str, args: dict[str, Any]) -> str:
        """Add a session allow-rule covering this call; return the rule added."""
        rule = self._rule_for(tool_name, args)
        if rule not in self.allow:
            self.allow.append(rule)
        return rule

    # -- rule matching ----------------------------------------------------

    def _matches_any(
        self, rules: list[str], tool_name: str, args: dict[str, Any], tool=None
    ) -> bool:
        return any(self._match(rule, tool_name, args, tool) for rule in rules)

    def _match(self, rule: str, tool_name: str, args: dict[str, Any], tool=None) -> bool:
        if rule.endswith(")") and "(" in rule:
            name, target = rule[:-1].split("(", 1)
            return name == tool_name and fnmatch(self._target(tool_name, args, tool), target)
        return rule == tool_name

    @staticmethod
    def _target(tool_name: str, args: dict[str, Any], tool=None) -> str:
        """The string a ``tool(glob)`` rule matches against.

        Prefer the tool's own :meth:`~agent.types.Tool.permission_target`; fall back to the
        name-based map for the built-ins when no tool object is available.
        """
        if tool is not None:
            return tool.permission_target(args)
        if tool_name == "bash":
            return str(args.get("command", ""))
        if tool_name == "web_fetch":
            return str(args.get("url", ""))
        if tool_name == "web_search":
            return str(args.get("query", ""))
        return str(args.get("path", ""))

    def _rule_for(self, tool_name: str, args: dict[str, Any]) -> str:
        """Build an allow-rule for 'always': scope bash to its first word, else the tool."""
        if tool_name == "bash":
            command = str(args.get("command", "")).strip()
            first = command.split()[0] if command else ""
            return f"bash({first} *)" if first else "bash"
        return tool_name
