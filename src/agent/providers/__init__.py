"""Native Python provider layer (Providers Phase 1).

Talks directly to provider HTTP APIs over httpx — no Node, no shim. Phase 1 ships the
OpenAI-compatible backend (`openai-completions`), which covers OpenAI and most local /
OpenAI-compatible servers. Anthropic (`anthropic-messages`) is Phase 2; until then it routes
to the transitional pi backend (see ``PROVIDERS.md``).
"""

from __future__ import annotations

from .base import Provider
from .catalog import Route, model_meta, route_for
from .errors import ProviderError
from .openai_compat import OpenAICompatProvider

__all__ = [
    "Provider",
    "ProviderError",
    "OpenAICompatProvider",
    "Route",
    "route_for",
    "model_meta",
    "NATIVE_APIS",
]

#: API flavors the native layer implements today. Others fall back to the pi backend.
NATIVE_APIS = frozenset({"openai-completions"})
