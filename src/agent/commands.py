"""Slash commands — REPL commands and custom markdown commands, modeled on Claude Code.

A line beginning with ``/`` is a command. Built-ins control the session (``/help``,
``/clear``, ``/model``, ``/tools``, ``/mode``, ``/exit``). **Custom commands** are markdown
files under ``.pya/commands/`` (project) or ``~/.pya/commands/`` (user), exactly like
Claude Code's ``.claude/commands/`` — the file name is the command, the body is a prompt
template with ``$ARGUMENTS`` (and ``$1``, ``$2``, …) substitution, and optional YAML-ish
frontmatter (``description``, ``argument-hint``).

A command either handles itself and returns control to the prompt, or returns a ``prompt``
to run as the next agent turn (this is what markdown commands do).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from rich.console import Console

from .permissions import PermissionMode, Permissions
from .types import AgentMessage, Tool

if TYPE_CHECKING:
    from .model import Model

__all__ = [
    "CommandContext",
    "CommandOutcome",
    "SlashCommand",
    "SlashRegistry",
    "build_registry",
    "load_markdown_commands",
]


@dataclass
class CommandContext:
    """Live session state a command may read or mutate."""

    console: Console
    history: list[AgentMessage]
    tools: list[Tool]
    permissions: Permissions
    model: "Model"
    registry: "SlashRegistry"


@dataclass
class CommandOutcome:
    """What a command asks the REPL to do next."""

    prompt: str | None = None  # run this as a user turn
    exit: bool = False


CommandRun = Callable[[CommandContext, str], "CommandOutcome | None"]


@dataclass
class SlashCommand:
    name: str
    description: str
    run: CommandRun
    argument_hint: str | None = None
    custom: bool = False


class SlashRegistry:
    """Holds commands by name and dispatches ``/...`` lines."""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        self._commands[command.name] = command

    def get(self, name: str) -> SlashCommand | None:
        return self._commands.get(name)

    def commands(self) -> list[SlashCommand]:
        return sorted(self._commands.values(), key=lambda c: c.name)

    def dispatch(self, line: str, ctx: CommandContext) -> CommandOutcome:
        """Handle a line that starts with ``/``."""
        name, _, args = line[1:].strip().partition(" ")
        command = self._commands.get(name)
        if command is None:
            ctx.console.print(f"[red]Unknown command:[/red] /{name} — try /help")
            return CommandOutcome()
        return command.run(ctx, args.strip()) or CommandOutcome()


# ---------------------------------------------------------------------------
# Built-in commands
# ---------------------------------------------------------------------------


def _cmd_help(ctx: CommandContext, args: str) -> CommandOutcome:
    ctx.console.print("[bold]Commands[/bold]")
    for command in ctx.registry.commands():
        hint = f" [dim]{command.argument_hint}[/dim]" if command.argument_hint else ""
        tag = " [dim](custom)[/dim]" if command.custom else ""
        ctx.console.print(f"  [cyan]/{command.name}[/cyan]{hint} — {command.description}{tag}")
    return CommandOutcome()


def _cmd_clear(ctx: CommandContext, args: str) -> CommandOutcome:
    ctx.history.clear()
    ctx.console.print("[dim]conversation cleared[/dim]")
    return CommandOutcome()


def _cmd_exit(ctx: CommandContext, args: str) -> CommandOutcome:
    return CommandOutcome(exit=True)


def _cmd_tools(ctx: CommandContext, args: str) -> CommandOutcome:
    ctx.console.print("[bold]Tools[/bold]")
    for tool in ctx.tools:
        ctx.console.print(f"  [cyan]{tool.name}[/cyan] — {tool.description}")
    return CommandOutcome()


def _cmd_model(ctx: CommandContext, args: str) -> CommandOutcome:
    if not args:
        ctx.console.print(f"current model: [cyan]{ctx.model.name}[/cyan]")
        return CommandOutcome()
    provider, model = args.split("/", 1) if "/" in args else (None, args)
    ctx.model.set_model(model, provider)
    ctx.console.print(f"model → [cyan]{ctx.model.name}[/cyan]")
    return CommandOutcome()


def _cmd_mode(ctx: CommandContext, args: str) -> CommandOutcome:
    if not args:
        ctx.console.print(f"permission mode: [cyan]{ctx.permissions.mode.value}[/cyan]")
        return CommandOutcome()
    try:
        ctx.permissions.mode = PermissionMode(args)
    except ValueError:
        options = ", ".join(m.value for m in PermissionMode)
        ctx.console.print(f"[red]Unknown mode:[/red] {args} — choose one of: {options}")
        return CommandOutcome()
    ctx.console.print(f"permission mode → [cyan]{args}[/cyan]")
    return CommandOutcome()


def _builtin_commands() -> list[SlashCommand]:
    return [
        SlashCommand("help", "show available commands", _cmd_help),
        SlashCommand("clear", "start a fresh conversation", _cmd_clear),
        SlashCommand("exit", "leave the REPL", _cmd_exit),
        SlashCommand("quit", "leave the REPL", _cmd_exit),
        SlashCommand("tools", "list the available tools", _cmd_tools),
        SlashCommand("model", "show or switch the model", _cmd_model, argument_hint="[provider/]model"),
        SlashCommand("mode", "show or set the permission mode", _cmd_mode, argument_hint="<mode>"),
    ]


# ---------------------------------------------------------------------------
# Custom markdown commands
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a leading ``---`` YAML-ish block (simple ``key: value`` lines) from the body."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    body = text[end + 4 :].lstrip("\n")
    return meta, body


def _expand(template: str, args: str) -> str:
    """Substitute ``$ARGUMENTS`` (all args) and ``$1``, ``$2``, … (positional)."""
    out = template.replace("$ARGUMENTS", args)
    parts = args.split()
    # High indices first so "$1" doesn't clobber "$10".
    for i in range(len(parts), 0, -1):
        out = out.replace(f"${i}", parts[i - 1])
    return out


def _make_markdown_command(path: Path, base: Path) -> SlashCommand:
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    name = path.relative_to(base).with_suffix("").as_posix().replace("/", ":")
    description = meta.get("description") or f"custom command from {path.name}"

    def run(ctx: CommandContext, args: str, _body: str = body) -> CommandOutcome:
        return CommandOutcome(prompt=_expand(_body, args).strip())

    return SlashCommand(name, description, run, argument_hint=meta.get("argument-hint"), custom=True)


def load_markdown_commands(dirs: list[Path]) -> list[SlashCommand]:
    """Load ``*.md`` command files from each directory (recursively)."""
    commands: list[SlashCommand] = []
    for directory in dirs:
        base = Path(directory)
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            commands.append(_make_markdown_command(path, base))
    return commands


def build_registry(cwd: str | Path = ".", *, extra_dirs: list[Path] | None = None) -> SlashRegistry:
    """Build a registry: custom markdown commands first, then built-ins (which win on name).

    Project commands (``<cwd>/.pya/commands``) override user commands
    (``~/.pya/commands``); built-ins always take precedence over custom.
    """
    registry = SlashRegistry()

    search = [Path.home() / ".pya" / "commands", Path(cwd) / ".pya" / "commands"]
    if extra_dirs:
        search += list(extra_dirs)
    custom: dict[str, SlashCommand] = {}
    for command in load_markdown_commands(search):
        custom[command.name] = command  # later dirs override earlier (project > user)
    for command in custom.values():
        registry.register(command)

    for command in _builtin_commands():
        registry.register(command)
    return registry
