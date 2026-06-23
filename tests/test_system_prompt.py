"""Phase 6: system-prompt assembly."""

from __future__ import annotations

from pydantic import BaseModel

from coding_agent.system_prompt import build_system_prompt, load_project_context
from coding_agent.types import Tool, ToolResult


class _Args(BaseModel):
    x: str


class ToolA(Tool):
    name = "a"
    description = "tool a"
    parameters = _Args
    prompt_snippet = "a: does A"
    prompt_guidelines = ("Shared guideline.", "A-specific guideline.")

    async def execute(self, args, *, on_update=None):
        return ToolResult(content="")


class ToolB(Tool):
    name = "b"
    description = "tool b"
    parameters = _Args
    prompt_snippet = "b: does B"
    prompt_guidelines = ("Shared guideline.",)  # duplicate of ToolA's

    async def execute(self, args, *, on_update=None):
        return ToolResult(content="")


def test_prompt_lists_tools_and_dedupes_guidelines():
    prompt = build_system_prompt([ToolA(), ToolB()], cwd=".", today="2026-06-23")
    assert "- a: does A" in prompt
    assert "- b: does B" in prompt
    # The shared guideline appears exactly once.
    assert prompt.count("Shared guideline.") == 1
    assert "A-specific guideline." in prompt
    assert "Current date: 2026-06-23" in prompt
    assert "Working directory:" in prompt


def test_custom_and_append():
    prompt = build_system_prompt(
        [], cwd=".", custom="CUSTOM PERSONA", append="EXTRA", today="2026-06-23"
    )
    assert prompt.startswith("CUSTOM PERSONA")
    assert "EXTRA" in prompt


def test_project_context_auto_loaded(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Project rules here.")
    prompt = build_system_prompt([], cwd=tmp_path, today="2026-06-23")
    assert "<project_context>" in prompt
    assert "Project rules here." in prompt


def test_load_project_context_prefers_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("agents")
    (tmp_path / "CLAUDE.md").write_text("claude")
    assert load_project_context(tmp_path) == "agents"


def test_no_project_context_when_absent(tmp_path):
    prompt = build_system_prompt([], cwd=tmp_path, today="2026-06-23")
    assert "<project_context>" not in prompt
