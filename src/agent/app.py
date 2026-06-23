"""Interactive REPL and one-shot runner.

Wires the pieces together: build the system prompt, open a model, and drive
:func:`agent.loop.run_agent`, rendering events as they stream. Two modes:

* one-shot (``pya -p "do X"``) — run a single prompt and exit.
* REPL (``pya``) — a multi-turn conversation; the history persists across turns, so
  the agent remembers what it just did. Ctrl-C aborts the current turn; Ctrl-D / ``/exit``
  quits.

Policy lives here, not in the loop: this module builds the :class:`Permissions` and the
interactive approver that gates mutating tools (write/edit/bash) unless the mode or a
rule allows them.
"""

from __future__ import annotations

import asyncio
import signal

from rich.console import Console

from pi_py_sdk import PiError

from .commands import CommandContext, build_registry
from .loop import run_agent
from .model import open_model
from .permissions import PermissionMode, Permissions
from .render import Renderer, _summarize_args
from .system_prompt import build_system_prompt
from .tools import coding_tools
from .types import AgentMessage, user_message


def _make_approver(console: Console):
    """An interactive approver: prompt y (once) / a (always) / n (deny) on stdin."""

    async def approver(tool_name: str, args: dict, reason: str | None) -> str:
        summary = _summarize_args(args)
        try:
            answer = (
                await asyncio.to_thread(input, f"  allow {tool_name} {summary}? [y/N/a] ")
            ).strip().lower()
        except EOFError:
            return "deny"  # non-interactive: default to safe
        if answer in ("a", "always"):
            return "always"
        if answer in ("y", "yes"):
            return "once"
        return "deny"

    return approver


def run(
    *,
    provider: str,
    model: str,
    reasoning: str | None = None,
    cwd: str = ".",
    prompt: str | None = None,
    permission_mode: str = "default",
) -> int:
    """Entry point used by the CLI. Runs one-shot if ``prompt`` is given, else the REPL."""
    permissions = Permissions(mode=PermissionMode(permission_mode))
    try:
        if prompt is not None:
            return asyncio.run(
                _run_once(prompt, provider=provider, model=model, reasoning=reasoning, cwd=cwd, permissions=permissions)
            )
        return asyncio.run(
            _run_repl(provider=provider, model=model, reasoning=reasoning, cwd=cwd, permissions=permissions)
        )
    except KeyboardInterrupt:
        return 130
    except PiError as exc:
        Console(stderr=True).print(f"[red][error][/red] {exc}")
        return 1


async def _run_once(
    prompt: str, *, provider: str, model: str, reasoning: str | None, cwd: str, permissions: Permissions
) -> int:
    console = Console()
    tools = coding_tools(cwd)
    system_prompt = build_system_prompt(tools, cwd)
    history: list[AgentMessage] = [user_message(prompt)]
    renderer = Renderer(console)
    approver = _make_approver(console)
    async with open_model(provider=provider, model=model, reasoning=reasoning) as m:
        async for event in run_agent(
            m, tools, history, system_prompt=system_prompt, permissions=permissions, approver=approver
        ):
            renderer.handle(event)
    return 0


async def _run_repl(
    *, provider: str, model: str, reasoning: str | None, cwd: str, permissions: Permissions
) -> int:
    console = Console()
    tools = coding_tools(cwd)
    system_prompt = build_system_prompt(tools, cwd)
    history: list[AgentMessage] = []
    renderer = Renderer(console)
    approver = _make_approver(console)
    registry = build_registry(cwd)

    async with open_model(provider=provider, model=model, reasoning=reasoning) as m:
        ctx = CommandContext(
            console=console, history=history, tools=tools, permissions=permissions, model=m, registry=registry
        )
        console.print(f"[bold]py-agent[/bold] [dim]({m.name}, cwd={cwd}, perms={permissions.mode.value})[/dim]")
        console.print("[dim]Type a message, or /help. Ctrl-D to quit.[/dim]\n")
        while True:
            try:
                line = (await asyncio.to_thread(input, "› ")).strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            if not line:
                continue

            if line.startswith("/"):
                outcome = registry.dispatch(line, ctx)
                if outcome.exit:
                    break
                if outcome.prompt is None:
                    continue  # command handled itself
                prompt_to_run = outcome.prompt  # e.g. a markdown command expanded to a prompt
            else:
                prompt_to_run = line

            history.append(user_message(prompt_to_run))
            await _run_turn(m, tools, history, system_prompt, renderer, permissions, approver)
    return 0


async def _run_turn(model, tools, history, system_prompt, renderer: Renderer, permissions, approver) -> None:
    """Run one turn as a task so Ctrl-C (SIGINT) can cancel just that turn."""
    loop = asyncio.get_running_loop()

    async def consume() -> None:
        async for event in run_agent(
            model, tools, history, system_prompt=system_prompt, permissions=permissions, approver=approver
        ):
            renderer.handle(event)

    task = asyncio.create_task(consume())

    def cancel() -> None:
        if not task.done():
            task.cancel()

    have_handler = True
    try:
        loop.add_signal_handler(signal.SIGINT, cancel)
    except (NotImplementedError, RuntimeError):
        have_handler = False  # e.g. Windows / non-main thread — Ctrl-C just won't abort

    try:
        await task
    except asyncio.CancelledError:
        renderer.aborted()
    finally:
        if have_handler:
            try:
                loop.remove_signal_handler(signal.SIGINT)
            except (NotImplementedError, RuntimeError):
                pass
