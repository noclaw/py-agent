"""Defaults for the CLI/app.

The final fallbacks when neither a CLI flag nor `~/.pya/settings.toml` (see
:mod:`agent.settings`) specifies a value. Resolution order is: CLI flag → settings file →
these constants (with the context window also inferred per-model when unset).
"""

from __future__ import annotations

#: Default provider/model used when none is specified.
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-sonnet-4-6"

#: Default thinking level (one of minimal/low/medium/high/xhigh; ``None`` = provider default).
DEFAULT_REASONING: str | None = None

#: Tool-gating mode (see :class:`agent.permissions.PermissionMode`).
DEFAULT_PERMISSION_MODE = "default"

#: Transient-error retries per turn (0 disables auto-retry).
DEFAULT_MAX_RETRIES = 2

#: Context window (tokens) used to size compaction when not inferrable from the model.
DEFAULT_CONTEXT_WINDOW = 200_000

#: Whether auto-compaction and the sub-agent ``task`` tool are on by default.
DEFAULT_COMPACT = True
DEFAULT_SUBAGENT = True
