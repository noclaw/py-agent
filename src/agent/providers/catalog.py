"""A tiny static catalog of known providers (and a little model metadata).

This replaces pi-ai's large auto-generated catalog with just what the native layer needs to
*route* a request: for a given provider/model, which API flavor, base URL, and API-key env
var to use. Custom/local models bring their own ``api``/``baseUrl`` via ``.pya/models.json``
(see :mod:`agent.models_registry`) and don't need an entry here.

Phase 1 implements the ``openai-completions`` API natively; ``anthropic-messages`` routes to
the transitional pi backend until Providers Phase 2 (see ``PROVIDERS.md``).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Route", "route_for", "model_meta", "builtin_models", "KNOWN_PROVIDERS", "BUILTIN_MODELS"]


@dataclass(frozen=True)
class Route:
    """How to reach a provider: which API flavor, base URL, and env var holds the key."""

    api: str
    base_url: str
    env_var: str | None = None


#: Provider id -> how to reach it. OpenAI-compatible providers all use ``openai-completions``.
KNOWN_PROVIDERS: dict[str, Route] = {
    "openai": Route("openai-completions", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    "groq": Route("openai-completions", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "together": Route("openai-completions", "https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "openrouter": Route("openai-completions", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "deepseek": Route("openai-completions", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "xai": Route("openai-completions", "https://api.x.ai/v1", "XAI_API_KEY"),
    "anthropic": Route("anthropic-messages", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY"),
}

#: Minimal per-model metadata (context windows) for models we ship knowledge of. Optional —
#: used to size compaction when a model is known. Custom models carry their own in the spec.
MODEL_META: dict[str, dict[str, int]] = {
    "claude-opus-4-8": {"contextWindow": 1_000_000},
    "claude-opus-4-7": {"contextWindow": 1_000_000},
    "claude-sonnet-4-6": {"contextWindow": 1_000_000},
    "claude-haiku-4-5": {"contextWindow": 200_000},
    "claude-fable-5": {"contextWindow": 1_000_000},
    "gpt-5.1": {"contextWindow": 400_000},
    "gpt-5": {"contextWindow": 400_000},
    "gpt-4.1": {"contextWindow": 1_047_576},
    "gpt-4o": {"contextWindow": 128_000},
}

#: A small curated catalog of well-known models, shown by ``pya models`` and the ``/model``
#: picker without a network call. Selecting any other id still works (routing is by provider).
#: Local/custom models come from ``.pya/models.json`` (see :mod:`agent.models_registry`).
BUILTIN_MODELS: list[dict[str, str]] = [
    {"provider": "anthropic", "id": "claude-opus-4-8"},
    {"provider": "anthropic", "id": "claude-opus-4-7"},
    {"provider": "anthropic", "id": "claude-sonnet-4-6"},
    {"provider": "anthropic", "id": "claude-haiku-4-5"},
    {"provider": "anthropic", "id": "claude-fable-5"},
    {"provider": "openai", "id": "gpt-5.1"},
    {"provider": "openai", "id": "gpt-5"},
    {"provider": "openai", "id": "gpt-5-codex"},
    {"provider": "openai", "id": "gpt-4.1"},
    {"provider": "openai", "id": "gpt-4o"},
]


def builtin_models() -> list[dict[str, str]]:
    """The curated built-in model list (provider/id dicts) for listing & the picker."""
    return list(BUILTIN_MODELS)


def route_for(provider: str | None, model_id: str) -> Route | None:
    """Resolve the route for a built-in ``provider``/``model_id``, or ``None`` if unknown
    (the caller then falls back to the transitional pi backend)."""
    if provider and provider in KNOWN_PROVIDERS:
        return KNOWN_PROVIDERS[provider]
    return None


def model_meta(model_id: str) -> dict[str, int]:
    """Known metadata (e.g. ``contextWindow``) for ``model_id``; empty if unknown."""
    return MODEL_META.get(model_id, {})
