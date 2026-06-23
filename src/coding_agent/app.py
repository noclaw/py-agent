"""Interactive REPL and one-shot runner.

Wires the pieces together: build the system prompt, open a model, and drive
:func:`coding_agent.loop.run_agent`, rendering events as they stream. Two modes:

* one-shot (``pycoda -p "do X"``) — run a single prompt and exit.
* REPL (``pycoda``) — a multi-turn conversation; the history persists across turns, so
  the agent remembers what it just did. Ctrl-C aborts the current turn; Ctrl-D / ``/exit``
  quits.
"""

from __future__ import annotations

import asyncio
import signal

from rich.console import Console

from pi_py_sdk import PiError

from .loop import run_agent
from .model import open_model
from .render import Renderer
from .system_prompt import build_system_prompt
from .tools import coding_tools
from .types import AgentMessage, user_message

_HELP = """\
Commands:
  /help          show this help
  /clear         start a fresh conversation
  /exit, /quit   leave (or press Ctrl-D)
While the agent is working, press Ctrl-C to interrupt the current turn."""


def run(*, provider: str, model: str, reasoning: str | None = None, cwd: str = ".", prompt: str | None = None) -> int:
    """Entry point used by the CLI. Runs one-shot if ``prompt`` is given, else the REPL."""
    try:
        if prompt is not None:
            return asyncio.run(_run_once(prompt, provider=provider, model=model, reasoning=reasoning, cwd=cwd))
        return asyncio.run(_run_repl(provider=provider, model=model, reasoning=reasoning, cwd=cwd))
    except KeyboardInterrupt:
        return 130
    except PiError as exc:
        Console(stderr=True).print(f"[red][error][/red] {exc}")
        return 1


async def _run_once(prompt: str, *, provider: str, model: str, reasoning: str | None, cwd: str) -> int:
    tools = coding_tools(cwd)
    system_prompt = build_system_prompt(tools, cwd)
    history: list[AgentMessage] = [user_message(prompt)]
    renderer = Renderer()
    async with open_model(provider=provider, model=model, reasoning=reasoning) as m:
        async for event in run_agent(m, tools, history, system_prompt=system_prompt):
            renderer.handle(event)
    return 0


async def _run_repl(*, provider: str, model: str, reasoning: str | None, cwd: str) -> int:
    console = Console()
    tools = coding_tools(cwd)
    system_prompt = build_system_prompt(tools, cwd)
    history: list[AgentMessage] = []
    renderer = Renderer(console)

    async with open_model(provider=provider, model=model, reasoning=reasoning) as m:
        console.print(f"[bold]py-agent[/bold] [dim]({m.name}, cwd={cwd})[/dim]")
        console.print("[dim]Type a message, or /help. Ctrl-D to quit.[/dim]\n")
        while True:
            try:
                line = (await asyncio.to_thread(input, "› ")).strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            if not line:
                continue
            if line in ("/exit", "/quit"):
                break
            if line == "/help":
                console.print(_HELP)
                continue
            if line == "/clear":
                history.clear()
                console.print("[dim]conversation cleared[/dim]")
                continue

            history.append(user_message(line))
            await _run_turn(m, tools, history, system_prompt, renderer)
    return 0


async def _run_turn(model, tools, history, system_prompt, renderer: Renderer) -> None:
    """Run one turn as a task so Ctrl-C (SIGINT) can cancel just that turn."""
    loop = asyncio.get_running_loop()

    async def consume() -> None:
        async for event in run_agent(model, tools, history, system_prompt=system_prompt):
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
