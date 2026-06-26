"""Native Anthropic OAuth: PKCE, redirect parsing, refresh, login (manual), logout."""

from __future__ import annotations

import base64
import hashlib
import json
import time

import pytest

from agent.providers import oauth


@pytest.fixture
def store(tmp_path, monkeypatch):
    auth = tmp_path / "pya" / "auth.json"
    compat = tmp_path / "pi" / "auth.json"
    monkeypatch.setattr(oauth, "AUTH_PATH", auth)
    monkeypatch.setattr(oauth, "COMPAT_AUTH_PATH", compat)
    return auth, compat


def _write(path, cred):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"anthropic": cred}))


# --- pure helpers -----------------------------------------------------------


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = oauth._pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected


def test_authorize_url_params():
    url = oauth.authorize_url("CHAL", state="VER")
    assert url.startswith("https://claude.ai/oauth/authorize?")
    assert "code_challenge=CHAL" in url and "state=VER" in url
    assert "code_challenge_method=S256" in url and "response_type=code" in url


@pytest.mark.parametrize("text,expected", [
    ("http://localhost:53692/callback?code=abc&state=xyz", ("abc", "xyz")),
    ("abc#xyz", ("abc", "xyz")),
    ("code=abc&state=xyz", ("abc", "xyz")),
    ("justacode", ("justacode", None)),
    ("", (None, None)),
])
def test_parse_redirect(text, expected):
    assert oauth.parse_redirect(text) == expected


# --- token store + refresh --------------------------------------------------


def test_valid_token_returned_without_refresh(store):
    auth, _ = store
    _write(auth, {"type": "oauth", "access": "good", "expires": time.time() * 1000 + 3_600_000})
    assert oauth.anthropic_oauth_token() == "good"


def test_expired_token_is_refreshed_and_persisted(store, monkeypatch):
    auth, _ = store
    _write(auth, {"type": "oauth", "access": "old", "refresh": "R", "expires": time.time() * 1000 - 1000})

    def fake_post(body):
        assert body["grant_type"] == "refresh_token" and body["refresh_token"] == "R"
        return {"access_token": "new", "refresh_token": "R2", "expires_in": 3600}

    monkeypatch.setattr(oauth, "_post_token", fake_post)
    assert oauth.anthropic_oauth_token() == "new"
    saved = json.loads(auth.read_text())["anthropic"]
    assert saved["access"] == "new" and saved["refresh"] == "R2"


def test_compat_path_used_when_primary_missing(store):
    _, compat = store
    _write(compat, {"type": "oauth", "access": "from-pi", "expires": time.time() * 1000 + 3_600_000})
    assert oauth.anthropic_oauth_token() == "from-pi"


def test_no_token_returns_none(store):
    assert oauth.anthropic_oauth_token() is None


# --- login / logout ---------------------------------------------------------


def test_manual_login_persists_token(store, monkeypatch):
    auth, _ = store

    def fake_post(body):
        assert body["grant_type"] == "authorization_code" and body["code"] == "CODE"
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    monkeypatch.setattr(oauth, "_post_token", fake_post)
    # The pasted redirect carries state == verifier; mirror it back from the prompt.
    captured = {}

    def fake_prompt(_msg):
        # parse_redirect returns (code, state); state must equal the verifier in the URL.
        return f"CODE#{captured['verifier']}"

    real_pkce = oauth._pkce

    def spy_pkce():
        v, c = real_pkce()
        captured["verifier"] = v
        return v, c

    monkeypatch.setattr(oauth, "_pkce", spy_pkce)
    cred = oauth.login_anthropic(manual=True, opener=lambda url: None, prompt=fake_prompt, echo=lambda *a: None)
    assert cred["access"] == "AT"
    assert json.loads(auth.read_text())["anthropic"]["access"] == "AT"


def test_login_state_mismatch_aborts(store, monkeypatch):
    monkeypatch.setattr(oauth, "_post_token", lambda body: {"access_token": "x", "expires_in": 1})
    with pytest.raises(oauth.ProviderError):
        oauth.login_anthropic(
            manual=True, opener=lambda url: None,
            prompt=lambda _m: "CODE#WRONGSTATE", echo=lambda *a: None,
        )


def test_logout_removes_entry(store):
    auth, _ = store
    _write(auth, {"type": "oauth", "access": "x"})
    assert oauth.logout_anthropic() is True
    assert "anthropic" not in json.loads(auth.read_text())
    assert oauth.logout_anthropic() is False  # already gone
