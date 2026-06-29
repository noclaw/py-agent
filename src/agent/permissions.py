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

import json
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .types import Tool

__all__ = [
    "PermissionMode",
    "Decision",
    "Permissions",
    "PermissionStore",
    "READ_ONLY_TOOLS",
    "MUTATING_TOOLS",
]


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
READ_ONLY_TOOLS = frozenset(
    {"read", "grep", "find", "ls", "web_fetch", "web_search", "recall", "search_memory", "todo_write"}
)
#: Name-only fallback for the built-in tools that change the world → gated by mode/rules/approval.
MUTATING_TOOLS = frozenset({"write", "edit", "bash", "note"})

# Decision values returned by :meth:`Permissions.decide`.
Decision = str  # "allow" | "deny" | "ask"


@dataclass
class PermissionStore:
    """Persists allow/deny rules to ``<cwd>/.pya/permissions.json`` so they survive restarts.

    The file is a small JSON object — ``{"allow": [...], "deny": [...]}`` — mirroring the rest
    of ``.pya/`` (``models.json``, ``commands/``, ``skills/``). Wired into :class:`Permissions`
    so an "always" approval (or a ``/permissions`` edit) is written through automatically.
    """

    path: Path

    @classmethod
    def for_cwd(cls, cwd: str | Path = ".") -> "PermissionStore":
        """The project store at ``<cwd>/.pya/permissions.json``."""
        return cls(Path(cwd) / ".pya" / "permissions.json")

    def load(self) -> tuple[list[str], list[str]]:
        """Return ``(allow, deny)`` from disk; empty lists if the file is missing/unreadable."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [], []
        allow = [str(r) for r in data.get("allow", []) if isinstance(r, str)]
        deny = [str(r) for r in data.get("deny", []) if isinstance(r, str)]
        return allow, deny

    def save(self, allow: list[str], deny: list[str]) -> None:
        """Write ``allow``/``deny`` rules, creating ``.pya/`` if needed. Best-effort (ignores OSError)."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"allow": allow, "deny": deny}, indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            pass  # persistence is a convenience; never break a run over it


@dataclass
class Permissions:
    """Decides allow/deny/ask for tool calls; can learn session allow-rules.

    When ``store`` is set, learned/edited rules are persisted through it so they carry across
    sessions (see :class:`PermissionStore`).
    """

    mode: PermissionMode = PermissionMode.DEFAULT
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    read_only: frozenset[str] = READ_ONLY_TOOLS
    store: PermissionStore | None = None

    @classmethod
    def load(
        cls, cwd: str | Path = ".", *, mode: PermissionMode = PermissionMode.DEFAULT
    ) -> "Permissions":
        """Build a :class:`Permissions` seeded with the project's persisted rules.

        Reads ``<cwd>/.pya/permissions.json`` (if any) and keeps the store attached so later
        "always" approvals and ``/permissions`` edits are written back.
        """
        store = PermissionStore.for_cwd(cwd)
        allow, deny = store.load()
        return cls(mode=mode, allow=allow, deny=deny, store=store)

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
        """Add an allow-rule covering this call (persisting it); return the rule added."""
        rule = self._rule_for(tool_name, args)
        if rule not in self.allow:
            self.allow.append(rule)
            self._persist()
        return rule

    def add_rule(self, kind: str, rule: str) -> bool:
        """Add ``rule`` to the ``"allow"`` or ``"deny"`` list (persisting). Returns False if a no-op."""
        target = self.allow if kind == "allow" else self.deny
        if rule in target:
            return False
        target.append(rule)
        self._persist()
        return True

    def remove_rule(self, rule: str) -> bool:
        """Remove ``rule`` from both lists (persisting). Returns True if anything was removed."""
        removed = False
        for target in (self.allow, self.deny):
            if rule in target:
                target.remove(rule)
                removed = True
        if removed:
            self._persist()
        return removed

    def clear_rules(self) -> None:
        """Drop all allow/deny rules (persisting the empty set)."""
        self.allow.clear()
        self.deny.clear()
        self._persist()

    def _persist(self) -> None:
        if self.store is not None:
            self.store.save(self.allow, self.deny)

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
