"""Generic OAuth 2.0 (authorization-code + PKCE) toolkit for the provider layer.

Reusable building blocks for adding an OAuth-authenticated provider — e.g. an
OpenAI-compatible service that logs in via OAuth. **Provider-neutral and not wired to
anything today**: a provider supplies an :class:`OAuthConfig`, and this module runs the
PKCE flow (local callback server or manual paste), exchanges/refreshes tokens, and stores
them per-provider in ``~/.pya/auth.json``.

History: this began as the Anthropic Pro/Max login. That was removed once Anthropic stopped
applying subscription credits to standard API usage (an API key is the right Anthropic
credential now). The generic toolkit is kept for future OAuth providers; the Anthropic flow
can be re-added as an :class:`OAuthConfig` if that changes.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from .errors import ProviderError

__all__ = [
    "OAuthConfig",
    "generate_pkce",
    "parse_redirect",
    "build_authorize_url",
    "exchange_code",
    "refresh_token",
    "login",
    "read_token",
    "save_token",
    "clear_token",
    "current_access_token",
    "TOKEN_STORE",
]

#: Per-provider OAuth token store: ``{"<provider>": {type, access, refresh, expires}}``.
TOKEN_STORE = Path.home() / ".pya" / "auth.json"

_SKEW_MS = 60_000


@dataclass(frozen=True)
class OAuthConfig:
    """Everything provider-specific about an OAuth authorization-code + PKCE flow."""

    provider: str
    client_id: str
    authorize_url: str
    token_url: str
    redirect_uri: str
    scopes: str
    #: Extra params merged into the authorize URL (e.g. ``{"code": "true"}``).
    extra_authorize_params: dict[str, str] = field(default_factory=dict)
    #: Local callback server bind (used when ``redirect_uri`` points at ``127.0.0.1``).
    callback_host: str = "127.0.0.1"
    callback_port: int = 53692
    callback_path: str = "/callback"


def _now_ms() -> float:
    return time.time() * 1000


# --- token store ------------------------------------------------------------


def _read_store() -> dict[str, Any]:
    try:
        return json.loads(TOKEN_STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_token(provider: str) -> dict[str, Any] | None:
    cred = _read_store().get(provider)
    return cred if isinstance(cred, dict) else None


def save_token(provider: str, cred: dict[str, Any]) -> None:
    store = _read_store()
    store[provider] = cred
    TOKEN_STORE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_STORE.write_text(json.dumps(store, indent=2), encoding="utf-8")


def clear_token(provider: str) -> bool:
    """Remove a provider's stored token. Returns whether one existed."""
    store = _read_store()
    if provider not in store:
        return False
    del store[provider]
    TOKEN_STORE.write_text(json.dumps(store, indent=2), encoding="utf-8")
    return True


# --- token endpoint ---------------------------------------------------------


def _post_token(config: OAuthConfig, body: dict[str, Any]) -> dict[str, Any]:
    resp = httpx.post(
        config.token_url, json=body,
        headers={"content-type": "application/json", "accept": "application/json"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _cred(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "oauth",
        "access": data["access_token"],
        "refresh": data.get("refresh_token", ""),
        "expires": _now_ms() + int(data.get("expires_in", 0)) * 1000 - 5 * 60 * 1000,
    }


def exchange_code(config: OAuthConfig, code: str, state: str, verifier: str) -> dict[str, Any]:
    try:
        data = _post_token(config, {
            "grant_type": "authorization_code",
            "client_id": config.client_id,
            "code": code,
            "state": state,
            "redirect_uri": config.redirect_uri,
            "code_verifier": verifier,
        })
        return _cred(data)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise ProviderError(f"OAuth token exchange failed: {exc}") from exc


def refresh_token(config: OAuthConfig, refresh: str) -> dict[str, Any] | None:
    try:
        data = _post_token(config, {
            "grant_type": "refresh_token", "client_id": config.client_id, "refresh_token": refresh,
        })
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    cred = _cred(data)
    if not cred["refresh"]:
        cred["refresh"] = refresh  # reuse if the server didn't rotate it
    return cred


def current_access_token(config: OAuthConfig) -> str | None:
    """The current access token for ``config.provider`` (refreshing if expired), or ``None``."""
    cred = read_token(config.provider)
    if not cred or cred.get("type") != "oauth":
        return None
    access, expires = cred.get("access"), cred.get("expires")
    if access and isinstance(expires, (int, float)) and expires > _now_ms() + _SKEW_MS:
        return access
    if cred.get("refresh"):
        refreshed = refresh_token(config, cred["refresh"])
        if refreshed:
            save_token(config.provider, refreshed)
            return refreshed["access"]
    return access


# --- PKCE + login -----------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorize_url(config: OAuthConfig, challenge: str, state: str) -> str:
    params = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": config.redirect_uri,
        "scope": config.scopes,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        **config.extra_authorize_params,
    }
    return f"{config.authorize_url}?{urllib.parse.urlencode(params)}"


def parse_redirect(text: str) -> tuple[str | None, str | None]:
    """Pull (code, state) from a pasted redirect URL, ``code#state``, or a bare code."""
    value = text.strip()
    if not value:
        return None, None
    if "://" in value or value.startswith("/"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
        return (q.get("code", [None])[0], q.get("state", [None])[0])
    if "#" in value:
        code, _, state = value.partition("#")
        return code or None, state or None
    if "code=" in value:
        q = urllib.parse.parse_qs(value)
        return (q.get("code", [None])[0], q.get("state", [None])[0])
    return value, None


def _start_callback_server(config: OAuthConfig, expected_state: str, holder: dict[str, str]):
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != config.callback_path:
                self.send_error(404)
                return
            q = urllib.parse.parse_qs(parsed.query)
            code, state = q.get("code", [None])[0], q.get("state", [None])[0]
            ok = bool(code) and state == expected_state
            if ok:
                holder["code"], holder["state"] = code, state  # type: ignore[assignment]
            msg = "Login complete — you can close this tab." if ok else "Login failed; try --manual."
            body = f"<html><body style='font-family:sans-serif;padding:2rem'>{msg}</body></html>".encode()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            if ok:
                done.set()

        def log_message(self, *args: Any) -> None:  # silence the access log
            del args

    server = http.server.HTTPServer((config.callback_host, config.callback_port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, done


def login(
    config: OAuthConfig,
    *,
    manual: bool = False,
    timeout: float = 300.0,
    opener: Callable[[str], Any] = webbrowser.open,
    prompt: Callable[[str], str] = input,
    echo: Callable[[str], Any] = print,
) -> dict[str, Any]:
    """Run the OAuth login flow for ``config`` and persist the token. Returns the credential."""
    verifier, challenge = generate_pkce()
    url = build_authorize_url(config, challenge, state=verifier)

    if manual:
        echo(f"Open this URL, approve, then paste the resulting URL (or code):\n\n{url}\n")
        try:
            opener(url)
        except Exception:  # noqa: BLE001 — opening a browser is best-effort
            pass
        code, state = parse_redirect(prompt("Paste redirect URL or code: "))
    else:
        holder: dict[str, str] = {}
        try:
            server, done = _start_callback_server(config, verifier, holder)
        except OSError as exc:
            raise ProviderError(
                f"Couldn't start the callback server on {config.callback_host}:{config.callback_port} "
                f"({exc}). Re-run with --manual."
            ) from exc
        echo(f"Opening your browser to log in…\n\nIf it doesn't open, visit:\n{url}\n")
        try:
            opener(url)
        except Exception:  # noqa: BLE001
            pass
        try:
            if not done.wait(timeout):
                raise ProviderError("Login timed out. Re-run with --manual.")
        finally:
            server.shutdown()
        code, state = holder.get("code"), holder.get("state")

    if not code:
        raise ProviderError("No authorization code received.")
    if state and state != verifier:
        raise ProviderError("OAuth state mismatch — aborting for safety.")
    cred = exchange_code(config, code, state or verifier, verifier)
    save_token(config.provider, cred)
    return cred
