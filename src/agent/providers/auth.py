"""Credential resolution for the native provider layer.

Phase 1: an explicit key in the model spec (custom/local models) wins, else the provider's
environment variable. OAuth (Claude Pro/Max, Codex) lands in Providers Phase 2 — see
``PROVIDERS.md``. Returns ``None`` when no key is found; a local server that needs no auth
works fine without one.
"""

from __future__ import annotations

import os
from typing import Any

from .catalog import Route

__all__ = ["resolve_api_key"]


def resolve_api_key(route: Route, spec: dict[str, Any] | None, provider: str | None = None) -> str | None:
    """Resolve the API key, in order: explicit spec ``apiKey`` > the provider's env var >
    the stored key from ``pya auth set`` (``~/.pya/auth.json``) > ``~/.pya/settings.toml`` >
    ``None``. (Env overrides the stored/file keys — handy for CI.)"""
    if spec and spec.get("apiKey"):
        return str(spec["apiKey"])
    if route.env_var:
        key = os.environ.get(route.env_var)
        if key:
            return key
    if provider:
        from . import oauth

        stored = oauth.get_api_key(provider)
        if stored:
            return stored

        from ..settings import load

        key = load().api_key(provider)
        if key:
            return key
    return None
