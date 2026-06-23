"""py-agent: a readable Python coding agent.

The agent **loop and tools are written in Python** (this package); the **model layer**
— providers, auth, transports, local models — is delegated to Pi's ``pi-ai`` through the
``pi-py`` SDK's :class:`~pi_py_sdk.model.PiModelClient`.

It is meant as an example implementation: small enough to read while learning Python,
and a clean starting point for personal-assistant / second-brain agents (swap the
coding toolset for your own via :mod:`agent.tools`).

See ``PLAN.md`` for the phased roadmap.
"""

from __future__ import annotations

__version__ = "0.0.1"

__all__ = ["__version__"]
