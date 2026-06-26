"""Native Python provider layer.

Talks directly to provider HTTP APIs over httpx — no Node, no shim, no SDK. Ships two
backends: ``openai-completions`` (OpenAI + most local / OpenAI-compatible servers) and
``anthropic-messages`` (Claude). Custom transports plug in via the :class:`Provider`
protocol and a ``.pya/models.json`` entry.
"""

from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import Provider
from .catalog import Route, builtin_models, model_meta, route_for
from .errors import ProviderError
from .openai_compat import OpenAICompatProvider

__all__ = [
    "Provider",
    "ProviderError",
    "OpenAICompatProvider",
    "AnthropicProvider",
    "Route",
    "route_for",
    "model_meta",
    "builtin_models",
    "NATIVE_APIS",
]

#: API flavors the native layer implements. Others must be added via a custom Provider.
NATIVE_APIS = frozenset({"openai-completions", "anthropic-messages"})
