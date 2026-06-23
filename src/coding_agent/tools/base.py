"""Shared tool plumbing (Phase 4).

Will hold the ``Tool`` protocol/base, the ``ToolResult`` shape, output truncation helpers
(max lines / max bytes), and path resolution relative to the working directory. Concrete
tools (read/write/edit/bash/grep/find/ls) build on this.

Port target: ``packages/coding-agent/src/core/tools/`` (``truncate.ts``, ``path-utils.ts``,
the per-tool ``ToolDefinition`` shape).
"""

from __future__ import annotations
