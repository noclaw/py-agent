"""Skills: discovery, the system-prompt block, and /skills + /skill:<name> commands."""

from __future__ import annotations

import io

from rich.console import Console

from agent.commands import CommandContext, build_registry
from agent.model import Model
from agent.permissions import Permissions
from agent.skills import discover_skills, format_skills_for_prompt
from agent.system_prompt import build_system_prompt
from agent.tools import coding_tools


def _write_skill(root, name, *, description="", frontmatter_name=None, body="Do the thing."):
    skill_dir = root / ".pya" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm_name = frontmatter_name or name
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {fm_name}\ndescription: {description}\n---\n{body}"
    )
    return skill_dir / "SKILL.md"


def test_discover_reads_frontmatter(tmp_path):
    _write_skill(tmp_path, "pdf", description="Work with PDF files")
    skills = discover_skills(tmp_path)
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "pdf"
    assert skill.description == "Work with PDF files"
    assert skill.source == "project"
    assert skill.path.is_absolute() and skill.path.name == "SKILL.md"


def test_discover_name_falls_back_to_dir(tmp_path):
    skill_dir = tmp_path / ".pya" / "skills" / "fromdir"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("no frontmatter here")
    skills = discover_skills(tmp_path)
    assert skills[0].name == "fromdir"


def test_no_skills_when_absent(tmp_path):
    assert discover_skills(tmp_path) == []


def test_format_skills_block():
    from agent.skills import Skill
    from pathlib import Path

    skills = [Skill(name="pdf", description="PDFs", path=Path("/x/SKILL.md"), source="project")]
    block = format_skills_for_prompt(skills)
    assert "<available_skills>" in block
    assert 'name="pdf"' in block and "PDFs" in block and "/x/SKILL.md" in block
    assert format_skills_for_prompt([]) == ""


def test_system_prompt_includes_skills(tmp_path):
    _write_skill(tmp_path, "pdf", description="Work with PDFs")
    skills = discover_skills(tmp_path)
    prompt = build_system_prompt(coding_tools(tmp_path), tmp_path, skills=skills, today="2026-06-23")
    assert "<available_skills>" in prompt
    assert "Work with PDFs" in prompt


def _ctx(cwd, skills):
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=200)
    registry = build_registry(cwd, skills=skills)
    model = Model(None, provider="anthropic", model="claude-sonnet-4-6")  # type: ignore[arg-type]
    ctx = CommandContext(
        console=console, history=[], tools=coding_tools(cwd), permissions=Permissions(),
        model=model, registry=registry, cwd=str(cwd),
    )
    return ctx, buffer, registry


def test_skills_command_lists(tmp_path):
    _write_skill(tmp_path, "pdf", description="Work with PDFs")
    skills = discover_skills(tmp_path)
    ctx, buf, registry = _ctx(tmp_path, skills)
    registry.dispatch("/skills", ctx)
    out = buf.getvalue()
    assert "pdf" in out and "Work with PDFs" in out


def test_skill_invoke_returns_body_as_prompt(tmp_path):
    _write_skill(tmp_path, "greet", description="Greeting", body="Greet $1 warmly.")
    skills = discover_skills(tmp_path)
    ctx, buf, registry = _ctx(tmp_path, skills)
    assert registry.get("skill:greet") is not None
    out = registry.dispatch("/skill:greet Alice", ctx)
    assert out.prompt == "Greet Alice warmly."
