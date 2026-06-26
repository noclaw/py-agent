"""Anthropic OAuth (Claude Pro/Max) — native login, refresh, and token store.

No `pi` and no Node: `pya login` runs the PKCE authorization-code flow itself (a local
callback server, or a pasted redirect URL), stores the token in `~/.pya/auth.json`, and
`pya logout` clears it. At runtime, :func:`anthropic_oauth_token` returns the current access
token, refreshing it when expired. When no `ANTHROPIC_API_KEY` is set, this is how the
Anthropic provider authenticates (Bearer + the `anthropic-beta: oauth-2025-04-20` header).

For drop-in compatibility we also read an existing `pi` login from `~/.pi/agent/auth.json`
if py-agent's own store is empty — but `pya login` writes only to `~/.pya/`.

The OAuth client parameters match Claude's public Pro/Max flow.
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
from pathlib import Path
from typing import Any, Callable

import httpx

from .errors import ProviderError

__all__ = ["anthropic_oauth_token", "login_anthropic", "logout_anthropic", "AUTH_PATH"]

#: py-agent's own token store (written by ``pya login``).
AUTH_PATH = Path.home() / ".pya" / "auth.json"
#: An existing ``pi`` login, read as a fallback only (never written).
COMPAT_AUTH_PATH = Path.home() / ".pi" / "agent" / "auth.json"

_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CALLBACK_PORT = 53692
_REDIRECT_URI = f"http://localhost:{_CALLBACK_PORT}/callback"
_SCOPES = (
    "org:create_api_key user:profile user:inference "
    "user:sessions:claude_code user:mcp_servers user:file_upload"
)
_SKEW_MS = 60_000


def _now_ms() -> float:
    return time.time() * 1000


# --- token store ------------------------------------------------------------


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _persist(cred: dict[str, Any]) -> None:
    auth = _read(AUTH_PATH)
    auth["anthropic"] = cred
    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_PATH.write_text(json.dumps(auth, indent=2), encoding="utf-8")


def anthropic_oauth_token() -> str | None:
    """The current Anthropic OAuth access token (refreshing if needed), or ``None``."""
    cred = _read(AUTH_PATH).get("anthropic") or _read(COMPAT_AUTH_PATH).get("anthropic")
    if not isinstance(cred, dict) or cred.get("type") != "oauth":
        return None
    access, expires = cred.get("access"), cred.get("expires")
    if access and isinstance(expires, (int, float)) and expires > _now_ms() + _SKEW_MS:
        return access
    refresh = cred.get("refresh")
    if refresh:
        refreshed = _refresh(refresh)
        if refreshed:
            _persist(refreshed)
            return refreshed["access"]
    return access  # fall back; the API reports an auth error if it's stale


# --- token endpoint ---------------------------------------------------------


def _post_token(body: dict[str, Any]) -> dict[str, Any]:
    resp = httpx.post(
        _TOKEN_URL, json=body,
        headers={"content-type": "application/json", "accept": "application/json"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _cred_from_token_response(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "oauth",
        "access": data["access_token"],
        "refresh": data.get("refresh_token", ""),
        # Match Claude's client: bake in a 5-minute safety margin.
        "expires": _now_ms() + int(data.get("expires_in", 0)) * 1000 - 5 * 60 * 1000,
    }


def _refresh(refresh_token: str) -> dict[str, Any] | None:
    try:
        data = _post_token(
            {"grant_type": "refresh_token", "client_id": _CLIENT_ID, "refresh_token": refresh_token}
        )
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    refreshed = _cred_from_token_response(data)
    if not refreshed.get("refresh"):
        refreshed["refresh"] = refresh_token  # reuse if the server didn't rotate it
    return refreshed


# --- PKCE + login -----------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def authorize_url(challenge: str, state: str) -> str:
    params = urllib.parse.urlencode({
        "code": "true",
        "client_id": _CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _REDIRECT_URI,
        "scope": _SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    return f"{_AUTHORIZE_URL}?{params}"


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


def _exchange(code: str, state: str, verifier: str) -> dict[str, Any]:
    try:
        data = _post_token({
            "grant_type": "authorization_code",
            "client_id": _CLIENT_ID,
            "code": code,
            "state": state,
            "redirect_uri": _REDIRECT_URI,
            "code_verifier": verifier,
        })
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError(f"OAuth token exchange failed: {exc}") from exc
    try:
        return _cred_from_token_response(data)
    except KeyError as exc:
        raise ProviderError(f"OAuth token response missing {exc}") from exc


def _start_callback_server(expected_state: str, holder: dict[str, str]) -> tuple[Any, threading.Event]:
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_error(404)
                return
            q = urllib.parse.parse_qs(parsed.query)
            code, state = q.get("code", [None])[0], q.get("state", [None])[0]
            ok = bool(code) and state == expected_state
            if ok:
                holder["code"], holder["state"] = code, state  # type: ignore[assignment]
            msg = "Login complete — you can close this tab." if ok else "Login failed; try `pya login --manual`."
            body = f"<html><body style='font-family:sans-serif;padding:2rem'>{msg}</body></html>".encode()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            if ok:
                done.set()

        def log_message(self, *args: Any) -> None:  # silence the default access log
            pass

    server = http.server.HTTPServer(("127.0.0.1", _CALLBACK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, done


def login_anthropic(
    *,
    manual: bool = False,
    timeout: float = 300.0,
    opener: Callable[[str], Any] = webbrowser.open,
    prompt: Callable[[str], str] = input,
    echo: Callable[[str], Any] = print,
) -> dict[str, Any]:
    """Run the OAuth login flow and persist the token. Returns the stored credential."""
    verifier, challenge = _pkce()
    url = authorize_url(challenge, state=verifier)

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
            server, done = _start_callback_server(verifier, holder)
        except OSError as exc:
            raise ProviderError(
                f"Couldn't start the local callback server on :{_CALLBACK_PORT} ({exc}). "
                f"Re-run with `pya login --manual`."
            ) from exc
        echo(f"Opening your browser to log in…\n\nIf it doesn't open, visit:\n{url}\n")
        try:
            opener(url)
        except Exception:  # noqa: BLE001
            pass
        try:
            if not done.wait(timeout):
                raise ProviderError("Login timed out. Re-run with `pya login --manual`.")
        finally:
            server.shutdown()
        code, state = holder.get("code"), holder.get("state")

    if not code:
        raise ProviderError("No authorization code received.")
    if state and state != verifier:
        raise ProviderError("OAuth state mismatch — aborting for safety.")
    cred = _exchange(code, state or verifier, verifier)
    _persist(cred)
    return cred


def logout_anthropic() -> bool:
    """Remove the stored Anthropic login from ``~/.pya/auth.json``. Returns whether one existed."""
    auth = _read(AUTH_PATH)
    if "anthropic" not in auth:
        return False
    del auth["anthropic"]
    AUTH_PATH.write_text(json.dumps(auth, indent=2), encoding="utf-8")
    return True
