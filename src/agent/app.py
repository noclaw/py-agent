"""Interactive REPL and one-shot runner.

Wires the pieces together: build the system prompt, open a model, and drive
:func:`agent.loop.run_agent`, rendering events as they stream. Two modes:

* one-shot (``pya -p "do X"``) — run a single prompt and exit.
* REPL (``pya``) — a multi-turn conversation; the history persists across turns, so
  the agent remembers what it just did. Ctrl-C aborts the current turn; Ctrl-D / ``/exit``
  quits.

Policy lives here, not in the loop: this module builds the :class:`Permissions` and the
interactive approver that gates mutating tools, and persists the conversation to a
:class:`~agent.sessions.Session` so it can be resumed with ``--continue`` / ``--resume``.
"""

from __future__ import annotations

import asyncio
import signal
import subprocess
from dataclasses import dataclass

from rich.console import Console

from .commands import CommandContext, build_registry
from .compaction import CompactionConfig, Compactor
from .hooks import HookResult, Hooks, UserPromptSubmit
from .loop import ContextTransform, run_agent
from .model import open_model
from .models_registry import ModelRegistry, load_model_registry, merge_catalog
from .permissions import PermissionMode, Permissions
from .providers import ProviderError
from .render import Renderer, _summarize_args
from .retry import RetryPolicy
from .sessions import Session, SessionStore
from .skills import discover_skills
from .system_prompt import build_system_prompt
from .tools import coding_tools, with_task_tool
from .types import AgentMessage, user_message


@dataclass
class _RunSettings:
    """The optional-feature toggles assembled by :func:`run` and threaded into a session."""

    hooks: Hooks | None
    retry: RetryPolicy | None
    compact: bool
    context_window: int
    subagent: bool


def _build_tools(model, cwd, permissions, approver, settings: _RunSettings):
    """The per-session tool list. The ``task`` sub-agent calls ``model``, so build it here
    (after :func:`open_model`)."""
    tools = coding_tools(cwd)
    if settings.subagent:
        tools = with_task_tool(
            tools, model=model, cwd=cwd, permissions=permissions, approver=approver
        )
    return tools


def _available_models(registry_models: ModelRegistry | None):
    """The model list for the ``/model`` picker: configured providers' models (from
    ``~/.pya/settings.toml`` when present, else the curated built-ins) + custom models from
    ``.pya/models.json``. No network call — works offline."""
    from .settings import catalog_models

    registry_models = registry_models or ModelRegistry()
    return merge_catalog(catalog_models(), registry_models)


def _make_transform(model, settings: _RunSettings) -> ContextTransform | None:
    """The optional compaction ``transform_context`` callback (``None`` when disabled)."""
    if not settings.compact:
        return None
    compactor = Compactor(model, CompactionConfig(max_tokens=settings.context_window))
    return compactor.transform


def _git_branch(cwd: str) -> str | None:
    """Current git branch of ``cwd`` (or ``None`` if not a repo / git is unavailable)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    branch = out.stdout.strip()
    return branch or None


def _build_default_hooks(cwd: str) -> Hooks:
    """A small demonstrative hook set: tag each prompt with the current git branch.

    This is the ``UserPromptSubmit`` seam in action — a hook may instead ``deny`` a prompt
    or inject other context (secrets redaction, repo state, etc.).
    """
    hooks = Hooks()

    @hooks.user_prompt_submit()
    def add_git_branch(event: UserPromptSubmit) -> HookResult | None:
        branch = _git_branch(cwd)
        return HookResult(additional_context=f"(current git branch: {branch})") if branch else None

    return hooks


async def _apply_prompt_submit(hooks: Hooks | None, prompt: str, console: Console) -> str | None:
    """Run ``UserPromptSubmit`` hooks. Returns the (possibly augmented) prompt, or ``None``
    if a hook blocked it."""
    if hooks is None:
        return prompt
    contexts: list[str] = []
    for result in await hooks.run(UserPromptSubmit(prompt)):
        if result.decision == "deny":
            console.print(f"[red]prompt blocked by hook:[/red] {result.reason or 'denied'}")
            return None
        if result.additional_context:
            contexts.append(result.additional_context)
    if contexts:
        prompt = prompt + "\n\n" + "\n".join(contexts)
    return prompt


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


def _resolve_session(
    store: SessionStore | None,
    cwd: str,
    provider: str,
    model: str,
    *,
    continue_session: bool,
    resume: str | None,
) -> tuple[Session | None, list[AgentMessage], str, str]:
    """Pick the session to use and load prior history.

    Returns (session, history, provider, model) — provider/model may be overridden to the
    resumed session's model so a continuation uses the same one.
    """
    if store is None:
        return None, [], provider, model

    target = resume or (store.latest(cwd) if continue_session else None)
    if target is not None:
        try:
            header, history, session = store.load(target)
            saved = header.get("model")
            if saved and "/" in saved:
                provider, model = saved.split("/", 1)
            return session, history, provider, model
        except FileNotFoundError:
            Console(stderr=True).print(f"[yellow]no session {target!r}; starting fresh[/yellow]")

    return store.create(cwd, f"{provider}/{model}"), [], provider, model


def run(
    *,
    provider: str,
    model: str,
    reasoning: str | None = None,
    cwd: str = ".",
    prompt: str | None = None,
    permission_mode: str = "default",
    continue_session: bool = False,
    resume: str | None = None,
    no_session: bool = False,
    hooks: Hooks | None = None,
    max_retries: int = 2,
    compact: bool = True,
    context_window: int = 200_000,
    subagent: bool = True,
) -> int:
    """Entry point used by the CLI. Runs one-shot if ``prompt`` is given, else the REPL.

    Args:
        hooks: optional hook set; defaults to a small demo set tagging prompts with the
            git branch (see :func:`_build_default_hooks`). Pass ``Hooks()`` to disable.
        max_retries: transient-error retries per turn (0 disables auto-retry).
        compact: auto-summarize old history as it nears ``context_window``.
        context_window: the model's context window, used to size compaction.
        subagent: expose a ``task`` tool that can spawn sub-agents.
    """
    permissions = Permissions(mode=PermissionMode(permission_mode))
    store = None if no_session else SessionStore()
    session, history, provider, model = _resolve_session(
        store, cwd, provider, model, continue_session=continue_session, resume=resume
    )
    if hooks is None:
        hooks = _build_default_hooks(cwd)
    retry = RetryPolicy(max_retries=max_retries) if max_retries > 0 else None
    settings = _RunSettings(
        hooks=hooks, retry=retry, compact=compact, context_window=context_window, subagent=subagent
    )
    # A custom/local model id (from ~/.pya/models.json) resolves to a full spec to stream.
    mreg = load_model_registry(cwd)
    info = mreg.resolve(provider, model)
    spec = info.spec if info else None
    try:
        if prompt is not None:
            return asyncio.run(
                _run_once(
                    prompt, provider=provider, model=model, spec=spec, reasoning=reasoning, cwd=cwd,
                    permissions=permissions, session=session, history=history, settings=settings,
                )
            )
        return asyncio.run(
            _run_repl(
                provider=provider, model=model, spec=spec, reasoning=reasoning, cwd=cwd, store=store,
                permissions=permissions, session=session, history=history, settings=settings,
                registry_models=mreg,
            )
        )
    except KeyboardInterrupt:
        return 130
    except ProviderError as exc:
        Console(stderr=True).print(f"[red][error][/red] {exc}")
        return 1


async def _run_once(
    prompt: str,
    *,
    provider: str,
    model: str,
    spec: dict | None = None,
    reasoning: str | None,
    cwd: str,
    permissions: Permissions,
    session: Session | None,
    history: list[AgentMessage],
    settings: _RunSettings,
) -> int:
    console = Console()
    renderer = Renderer(console)
    approver = _make_approver(console)
    async with open_model(provider=provider, model=model, spec=spec, reasoning=reasoning) as m:
        tools = _build_tools(m, cwd, permissions, approver, settings)
        transform = _make_transform(m, settings)
        system_prompt = build_system_prompt(tools, cwd, skills=discover_skills(cwd))
        submitted = await _apply_prompt_submit(settings.hooks, prompt, console)
        if submitted is None:
            return 1
        history.append(user_message(submitted))
        async for event in run_agent(
            m, tools, history, system_prompt=system_prompt, hooks=settings.hooks,
            permissions=permissions, approver=approver, retry=settings.retry,
            transform_context=transform,
        ):
            renderer.handle(event)
    if session is not None:
        session.append_new(history)
    return 0


async def _run_repl(
    *,
    provider: str,
    model: str,
    spec: dict | None = None,
    reasoning: str | None,
    cwd: str,
    store: SessionStore | None,
    permissions: Permissions,
    session: Session | None,
    history: list[AgentMessage],
    settings: _RunSettings,
    registry_models: ModelRegistry | None = None,
) -> int:
    console = Console()
    skills = discover_skills(cwd)
    renderer = Renderer(console)
    approver = _make_approver(console)
    registry = build_registry(cwd, skills=skills)

    async with open_model(provider=provider, model=model, spec=spec, reasoning=reasoning) as m:
        tools = _build_tools(m, cwd, permissions, approver, settings)
        system_prompt = build_system_prompt(tools, cwd, skills=skills)
        models = _available_models(registry_models)
        ctx = CommandContext(
            console=console, history=history, tools=tools, permissions=permissions, model=m,
            registry=registry, store=store, session=session, cwd=cwd, models=models,
        )
        console.print(f"[bold]py-agent[/bold] [dim]({m.name}, cwd={cwd}, perms={permissions.mode.value})[/dim]")
        if history:
            console.print(f"[dim]resumed {len(history)} messages[/dim]")
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

            submitted = await _apply_prompt_submit(settings.hooks, prompt_to_run, console)
            if submitted is None:
                continue
            history.append(user_message(submitted))
            await _run_turn(
                m, tools, history, system_prompt, renderer, permissions, approver, settings
            )
            # ctx.session may have been swapped by /resume or /clear.
            if ctx.session is not None:
                ctx.session.append_new(history)
    return 0


async def _run_turn(
    model, tools, history, system_prompt, renderer: Renderer, permissions, approver,
    settings: _RunSettings,
) -> None:
    """Run one turn as a task so Ctrl-C (SIGINT) can cancel just that turn."""
    loop = asyncio.get_running_loop()
    transform = _make_transform(model, settings)

    async def consume() -> None:
        async for event in run_agent(
            model, tools, history, system_prompt=system_prompt, hooks=settings.hooks,
            permissions=permissions, approver=approver, retry=settings.retry,
            transform_context=transform,
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
