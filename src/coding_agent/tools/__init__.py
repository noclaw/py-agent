"""Tool registry and bundles (Phase 4).

Port target: ``packages/coding-agent/src/core/tools/index.ts``.

Will expose a name->factory registry and bundle helpers — ``coding_tools(cwd)`` (the
default set: read/write/edit/bash) and ``read_only_tools(cwd)`` (adds grep/find/ls). This
package is the seam where second-brain / assistant users swap the coding toolset for
their own (e.g. note/recall/memory tools).
"""

from __future__ import annotations
