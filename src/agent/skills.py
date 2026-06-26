"""Skills — model-aware capabilities loaded from markdown, modeled on Claude Code.

A skill is a directory with a ``SKILL.md`` file: frontmatter (``name``, ``description``)
plus instructions in the body. Skills differ from slash commands: slash commands are
*user-invoked*; skills use **progressive disclosure** — only each skill's name and
description go into the system prompt, and the model reads the full ``SKILL.md`` (with the
``read`` tool) when a task matches. The body may reference sibling files/scripts in the
skill directory.

Discovery (project overrides user by name):
  - ``~/.pya/skills/<name>/SKILL.md``        (user)
  - ``<cwd>/.pya/skills/<name>/SKILL.md``    (project)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._markdown import parse_frontmatter

__all__ = ["Skill", "discover_skills", "format_skills_for_prompt", "skill_dirs"]

SKILL_FILE = "SKILL.md"


@dataclass
class Skill:
    name: str
    description: str
    path: Path  # absolute path to the SKILL.md the model should read
    source: str  # "user" | "project" | "extra"


def skill_dirs(cwd: str | Path, extra_dirs: list[Path] | None = None) -> list[tuple[Path, str]]:
    """The directories searched for skills, with their source label (user first)."""
    dirs: list[tuple[Path, str]] = [
        (Path.home() / ".pya" / "skills", "user"),
        (Path(cwd) / ".pya" / "skills", "project"),
    ]
    if extra_dirs:
        dirs += [(Path(d), "extra") for d in extra_dirs]
    return dirs


def discover_skills(cwd: str | Path = ".", *, extra_dirs: list[Path] | None = None) -> list[Skill]:
    """Find all skills available for ``cwd``. Later sources (project) override earlier ones."""
    found: dict[str, Skill] = {}
    for base, source in skill_dirs(cwd, extra_dirs):
        if not base.is_dir():
            continue
        for skill_md in sorted(base.glob(f"*/{SKILL_FILE}")):
            try:
                meta, _body = parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            name = meta.get("name") or skill_md.parent.name
            found[name] = Skill(
                name=name,
                description=meta.get("description", ""),
                path=skill_md.resolve(),
                source=source,
            )
    return list(found.values())


def format_skills_for_prompt(skills: list[Skill]) -> str:
    """Render the ``<available_skills>`` block injected into the system prompt.

    Only name/description/path appear here — the model reads the file for the full
    instructions (progressive disclosure).
    """
    if not skills:
        return ""
    lines = [
        "<available_skills>",
        "When a task matches a skill's description, read its file (with the read tool) for",
        "full instructions before proceeding.",
    ]
    for skill in skills:
        lines.append(f'  <skill name="{skill.name}" path="{skill.path}">{skill.description}</skill>')
    lines.append("</available_skills>")
    return "\n".join(lines)
