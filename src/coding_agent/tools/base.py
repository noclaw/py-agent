"""Shared tool plumbing.

The :class:`~coding_agent.types.Tool` protocol and :class:`~coding_agent.types.ToolResult`
live in :mod:`coding_agent.types` (re-exported here for convenience). Phase 4 adds the
rest of the shared helpers used by the concrete tools: output truncation (max lines / max
bytes), path resolution relative to the working directory, and a small ``ok()``/``err()``
result helper. Port target: ``packages/coding-agent/src/core/tools/`` (``truncate.ts``,
``path-utils.ts``).
"""

from __future__ import annotations

from ..types import Tool, ToolResult

__all__ = ["Tool", "ToolResult"]
