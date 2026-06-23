"""System-prompt builder (Phase 6).

Port target: ``packages/coding-agent/src/core/system-prompt.ts``.

``build_system_prompt(tools, cwd, ...)`` will assemble the prompt programmatically: base
persona + an "Available tools" list from each tool's ``prompt_snippet`` + a deduped
"Guidelines" list from each tool's ``prompt_guidelines`` + current date and cwd, plus an
optional ``<project_context>`` from an ``AGENTS.md``/``CLAUDE.md`` file. Built from the
tool set so adding a tool updates the prompt automatically.
"""

from __future__ import annotations
