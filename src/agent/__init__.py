"""py-agent: a readable Python coding agent.

**All of it is Python** (this package): the agent loop, the tools, and the model layer
(:mod:`agent.providers`), which talks directly to provider HTTP APIs over ``httpx`` —
OpenAI-compatible (OpenAI + local servers) and Anthropic. No Node, no subprocess.

It is meant as an example implementation: small enough to read while learning Python,
and a clean starting point for personal-assistant / second-brain agents (swap the
coding toolset for your own via :mod:`agent.tools`).

See ``PLAN.md`` for the phased roadmap.
"""

from __future__ import annotations

__version__ = "0.0.1"

__all__ = ["__version__"]
