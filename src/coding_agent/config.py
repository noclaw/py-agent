"""Configuration and defaults.

Phase 1 holds just the defaults the CLI needs. A full settings layer (file load/merge,
``models.json`` for custom/local models, credential notes) lands in a later phase — port
target: ``packages/coding-agent/src/config.ts`` and ``core/model-registry.ts``.
"""

from __future__ import annotations

#: Default provider/model used when none is specified. The latest Claude Sonnet is a
#: good balance of capability and cost for an example agent.
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-sonnet-4-6"

#: Default thinking level passed to the model (one of off/minimal/low/medium/high/xhigh;
#: ``None`` lets the provider decide).
DEFAULT_REASONING: str | None = None
