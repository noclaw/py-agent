"""Anthropic OAuth (Claude Pro/Max) — reuse an existing Pi login.

When no ``ANTHROPIC_API_KEY`` is set, fall back to the OAuth token a prior ``pi`` → ``/login``
stored at ``~/.pi/agent/auth.json`` (drop-in compatibility — same token store the old shim
used). The token is sent as ``Authorization: Bearer`` plus the ``anthropic-beta:
oauth-2025-04-20`` header (handled in :class:`~agent.providers.anthropic.AnthropicProvider`).

If the access token has expired, it's refreshed via Anthropic's OAuth token endpoint using
the stored refresh token and persisted back. Best-effort: on any failure we return the
(possibly stale) access token so the API surfaces a clear auth error.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

__all__ = ["anthropic_oauth_token", "AUTH_PATH"]

#: The token store written by the Pi coding agent's ``/login``.
AUTH_PATH = Path.home() / ".pi" / "agent" / "auth.json"

#: Claude Pro/Max OAuth client (the public client id used by the Pi/Claude Code login).
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
_SKEW_MS = 60_000  # refresh a minute early


def _now_ms() -> float:
    return time.time() * 1000


def _load() -> dict[str, Any]:
    try:
        return json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _persist(cred: dict[str, Any]) -> None:
    auth = _load()
    auth["anthropic"] = cred
    try:
        AUTH_PATH.write_text(json.dumps(auth, indent=2), encoding="utf-8")
    except OSError:
        pass  # read-only store just means we refresh again next time


def _refresh(refresh_token: str) -> dict[str, Any] | None:
    try:
        resp = httpx.post(
            _TOKEN_URL,
            json={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": _CLIENT_ID},
            headers={"content-type": "application/json"},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    access = data.get("access_token")
    if not access:
        return None
    return {
        "type": "oauth",
        "access": access,
        "refresh": data.get("refresh_token", refresh_token),
        "expires": _now_ms() + int(data.get("expires_in", 0)) * 1000,
    }


def anthropic_oauth_token() -> str | None:
    """The current Anthropic OAuth access token (refreshing if needed), or ``None``."""
    cred = _load().get("anthropic")
    if not isinstance(cred, dict) or cred.get("type") != "oauth":
        return None
    access = cred.get("access")
    expires = cred.get("expires")
    if access and isinstance(expires, (int, float)) and expires > _now_ms() + _SKEW_MS:
        return access  # still valid
    refresh = cred.get("refresh")
    if refresh:
        refreshed = _refresh(refresh)
        if refreshed:
            _persist(refreshed)
            return refreshed["access"]
    return access  # fall back; the API will report an auth error if it's stale
