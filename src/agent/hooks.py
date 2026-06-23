"""Hooks — user-supplied callbacks at key points in a run, modeled on Claude Code.

The event names and semantics mirror Claude Code so the concepts transfer:

* ``PreToolUse``  — before a tool runs. May ``allow`` (skip the permission check) or
  ``deny`` (block the call) it.
* ``PostToolUse`` — after a tool runs. May attach ``additional_context`` (extra text fed
  back to the model, e.g. linter output).
* ``UserPromptSubmit`` — when the user submits a prompt. May ``deny`` it or attach
  ``additional_context`` (extra text prepended to the message).

Unlike Claude Code (which runs external shell commands described in settings.json), hooks
here are plain Python callables — readable, and the natural extension point in a library.
A ``matcher`` (e.g. ``"bash"`` or ``"write|edit"``) limits a tool hook to certain tools.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Union

if TYPE_CHECKING:
    from .types import ToolResult

__all__ = [
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "HookResult",
    "Hooks",
]


@dataclass
class PreToolUse:
    """About to run a tool."""

    tool_name: str
    tool_input: dict[str, Any]
    tool_call_id: str


@dataclass
class PostToolUse:
    """A tool just finished."""

    tool_name: str
    tool_input: dict[str, Any]
    tool_call_id: str
    result: "ToolResult"


@dataclass
class UserPromptSubmit:
    """The user submitted a prompt."""

    prompt: str


HookEvent = Union[PreToolUse, PostToolUse, UserPromptSubmit]


@dataclass
class HookResult:
    """What a hook may return (``None`` means 'no opinion').

    ``decision`` applies to PreToolUse/UserPromptSubmit: ``"allow"`` or ``"deny"``.
    ``additional_context`` (PostToolUse/UserPromptSubmit) is extra text surfaced to the
    model.
    """

    decision: str | None = None  # "allow" | "deny" | None
    reason: str | None = None
    additional_context: str | None = None


HookCallback = Callable[[HookEvent], Union[HookResult, None, Awaitable[Union[HookResult, None]]]]

_EVENT_NAMES = {
    PreToolUse: "PreToolUse",
    PostToolUse: "PostToolUse",
    UserPromptSubmit: "UserPromptSubmit",
}


def _matches(matcher: str, tool_name: str) -> bool:
    """A matcher is one or more ``|``-separated globs against the tool name."""
    return any(fnmatch(tool_name, part.strip()) for part in matcher.split("|"))


class Hooks:
    """A registry of hook callbacks, grouped by event name.

        hooks = Hooks()

        @hooks.pre_tool_use(matcher="bash")
        def confirm_bash(event):
            if "rm -rf" in event.tool_input.get("command", ""):
                return HookResult(decision="deny", reason="refusing rm -rf")
    """

    def __init__(self) -> None:
        self._registry: dict[str, list[tuple[str | None, HookCallback]]] = {}

    def add(self, event: str, callback: HookCallback, *, matcher: str | None = None) -> None:
        """Register ``callback`` for an event ("PreToolUse"/"PostToolUse"/"UserPromptSubmit")."""
        self._registry.setdefault(event, []).append((matcher, callback))

    # Decorator sugar -----------------------------------------------------

    def pre_tool_use(self, matcher: str | None = None) -> Callable[[HookCallback], HookCallback]:
        return self._decorator("PreToolUse", matcher)

    def post_tool_use(self, matcher: str | None = None) -> Callable[[HookCallback], HookCallback]:
        return self._decorator("PostToolUse", matcher)

    def user_prompt_submit(self) -> Callable[[HookCallback], HookCallback]:
        return self._decorator("UserPromptSubmit", None)

    def _decorator(self, event: str, matcher: str | None) -> Callable[[HookCallback], HookCallback]:
        def register(callback: HookCallback) -> HookCallback:
            self.add(event, callback, matcher=matcher)
            return callback

        return register

    # Execution -----------------------------------------------------------

    async def run(self, event: HookEvent) -> list[HookResult]:
        """Run every hook registered for ``event`` (honoring matchers); collect results."""
        name = _EVENT_NAMES[type(event)]
        tool_name = getattr(event, "tool_name", None)
        results: list[HookResult] = []
        for matcher, callback in self._registry.get(name, []):
            if matcher and tool_name is not None and not _matches(matcher, tool_name):
                continue
            out = callback(event)
            if inspect.isawaitable(out):
                out = await out
            if out is not None:
                results.append(out)
        return results
