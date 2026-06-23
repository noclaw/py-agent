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

from ._markdown import parse_frontmatter
from .permissions import PermissionMode, Permissions
from .skills import Skill, discover_skills
from .types import AgentMessage, Tool

if TYPE_CHECKING:
    from .model import Model
    from .sessions import Session, SessionStore

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
    store: "SessionStore | None" = None
    session: "Session | None" = None
    cwd: str = "."


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
    if ctx.store is not None:  # subsequent messages go to a fresh session file
        ctx.session = ctx.store.create(ctx.cwd, ctx.model.name)
    ctx.console.print("[dim]conversation cleared[/dim]")
    return CommandOutcome()


def _cmd_sessions(ctx: CommandContext, args: str) -> CommandOutcome:
    if ctx.store is None:
        ctx.console.print("[dim]sessions are disabled[/dim]")
        return CommandOutcome()
    infos = ctx.store.list(ctx.cwd)
    if not infos:
        ctx.console.print("[dim]no saved sessions for this directory[/dim]")
        return CommandOutcome()
    ctx.console.print("[bold]Sessions[/bold] [dim](newest first)[/dim]")
    for info in infos:
        current = " [green](current)[/green]" if ctx.session and info.id == ctx.session.id else ""
        ctx.console.print(
            f"  [cyan]{info.id}[/cyan] [dim]{info.messages} msgs[/dim] {info.preview}{current}"
        )
    ctx.console.print("[dim]resume with /resume <id>[/dim]")
    return CommandOutcome()


def _cmd_resume(ctx: CommandContext, args: str) -> CommandOutcome:
    if ctx.store is None:
        ctx.console.print("[dim]sessions are disabled[/dim]")
        return CommandOutcome()
    if not args:
        return _cmd_sessions(ctx, "")
    try:
        header, messages, session = ctx.store.load(args)
    except FileNotFoundError:
        ctx.console.print(f"[red]session not found:[/red] {args}")
        return CommandOutcome()
    ctx.history.clear()
    ctx.history.extend(messages)
    ctx.session = session
    model = header.get("model")
    if model and "/" in model:
        provider, name = model.split("/", 1)
        ctx.model.set_model(name, provider)
    ctx.console.print(f"[dim]resumed {session.id} — {len(messages)} messages[/dim]")
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
        SlashCommand("sessions", "list saved sessions for this directory", _cmd_sessions),
        SlashCommand("resume", "resume a saved session", _cmd_resume, argument_hint="<id>"),
    ]


# ---------------------------------------------------------------------------
# Custom markdown commands
# ---------------------------------------------------------------------------


def _expand(template: str, args: str) -> str:
    """Substitute ``$ARGUMENTS`` (all args) and ``$1``, ``$2``, … (positional)."""
    out = template.replace("$ARGUMENTS", args)
    parts = args.split()
    # High indices first so "$1" doesn't clobber "$10".
    for i in range(len(parts), 0, -1):
        out = out.replace(f"${i}", parts[i - 1])
    return out


def _make_markdown_command(path: Path, base: Path) -> SlashCommand:
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
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


# ---------------------------------------------------------------------------
# Skill commands (/skills list, /skill:<name> invoke)
# ---------------------------------------------------------------------------


def _make_skills_command(skills: list[Skill]) -> SlashCommand:
    def run(ctx: CommandContext, args: str) -> CommandOutcome:
        if not skills:
            ctx.console.print("[dim]no skills found (add SKILL.md under .pya/skills/<name>/)[/dim]")
            return CommandOutcome()
        ctx.console.print("[bold]Skills[/bold]")
        for skill in skills:
            ctx.console.print(
                f"  [cyan]{skill.name}[/cyan] — {skill.description} [dim]({skill.source})[/dim]"
            )
        ctx.console.print("[dim]invoke with /skill:<name>, or just describe a matching task[/dim]")
        return CommandOutcome()

    return SlashCommand("skills", "list available skills", run)


def _make_skill_command(skill: Skill) -> SlashCommand:
    def run(ctx: CommandContext, args: str) -> CommandOutcome:
        # Read the SKILL.md body on demand and run it as a prompt (with arg substitution).
        try:
            _meta, body = parse_frontmatter(skill.path.read_text(encoding="utf-8"))
        except OSError as exc:
            ctx.console.print(f"[red]could not read skill {skill.name}:[/red] {exc}")
            return CommandOutcome()
        return CommandOutcome(prompt=_expand(body, args).strip())

    return SlashCommand(
        f"skill:{skill.name}", skill.description or f"skill {skill.name}", run, custom=True
    )


def build_registry(
    cwd: str | Path = ".",
    *,
    extra_dirs: list[Path] | None = None,
    skills: list[Skill] | None = None,
) -> SlashRegistry:
    """Build a registry: custom markdown + skill commands first, then built-ins (which win).

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

    if skills is None:
        skills = discover_skills(cwd)
    for skill in skills:
        registry.register(_make_skill_command(skill))

    for command in _builtin_commands():
        registry.register(command)
    registry.register(_make_skills_command(skills))  # after built-ins: needs the skills list
    return registry
