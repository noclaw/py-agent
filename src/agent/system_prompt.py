"""System-prompt builder.

Port target: ``packages/coding-agent/src/core/system-prompt.ts``.

The prompt is assembled programmatically from the tool set, so adding or removing a tool
updates it automatically: each tool contributes a one-line ``prompt_snippet`` to the
"Available tools" list and any ``prompt_guidelines`` to the deduped "Guidelines" list.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from .skills import Skill, format_skills_for_prompt
from .types import Tool

__all__ = ["build_system_prompt", "load_project_context"]

BASE_PERSONA = (
    "You are an expert coding assistant. You help the user by reading files, running "
    "shell commands, editing code, and writing new files in their project. Work in small "
    ", verifiable steps and use the tools rather than guessing."
)

#: Always-included guideline bullets (Pi adds similar ones unconditionally).
ALWAYS_ON_GUIDELINES = (
    "Be concise and direct; avoid unnecessary preamble.",
    "Show file paths clearly so the user can follow along.",
    "Prefer reading files and running commands to verify, rather than assuming.",
    "Stop and report once the task is done; don't keep calling tools needlessly.",
)

#: Project context files to auto-load (first match wins), like Pi's AGENTS.md/CLAUDE.md.
PROJECT_CONTEXT_FILES = ("AGENTS.md", "CLAUDE.md")


def _dedupe(items: list[str]) -> list[str]:
    """Order-preserving de-duplication."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def load_project_context(cwd: str | Path) -> str | None:
    """Return the contents of the first project context file found in ``cwd``, if any."""
    base = Path(cwd)
    for name in PROJECT_CONTEXT_FILES:
        path = base / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace").strip() or None
            except OSError:
                return None
    return None


def build_system_prompt(
    tools: list[Tool],
    cwd: str | Path = ".",
    *,
    custom: str | None = None,
    append: str | None = None,
    project_context: str | None = None,
    skills: list[Skill] | None = None,
    today: str | None = None,
) -> str:
    """Assemble the system prompt for a run.

    Args:
        tools: The tools available this run (drives the tool list + guidelines).
        cwd: Working directory (shown to the model, and used to find project context).
        custom: Replace the base persona entirely (the rest is still appended).
        append: Extra text appended after the guidelines.
        project_context: Project notes; if ``None``, auto-loaded from AGENTS.md/CLAUDE.md.
        skills: Available skills; only their name/description/path go in the prompt
            (the model reads each ``SKILL.md`` on demand — progressive disclosure).
        today: ISO date override (for deterministic tests).
    """
    parts: list[str] = [custom or BASE_PERSONA]

    snippets = [t.prompt_snippet for t in tools if t.prompt_snippet]
    if snippets:
        parts.append("## Available tools\n" + "\n".join(f"- {s}" for s in snippets))

    guidelines = _dedupe(
        [g for t in tools for g in t.prompt_guidelines] + list(ALWAYS_ON_GUIDELINES)
    )
    if guidelines:
        parts.append("## Guidelines\n" + "\n".join(f"- {g}" for g in guidelines))

    if skills:
        parts.append(format_skills_for_prompt(skills))

    if project_context is None:
        project_context = load_project_context(cwd)
    if project_context:
        parts.append(f"<project_context>\n{project_context}\n</project_context>")

    if append:
        parts.append(append)

    date = today or datetime.date.today().isoformat()
    parts.append(f"Current date: {date}\nWorking directory: {Path(cwd).resolve()}")

    return "\n\n".join(parts)
