"""The generic OAuth toolkit: PKCE, redirect parsing, token store, exchange/refresh, login.

Provider-neutral (not wired to any provider) — tested against a dummy OAuthConfig.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time

import pytest

from agent.providers import oauth

CONFIG = oauth.OAuthConfig(
    provider="demo",
    client_id="cid",
    authorize_url="https://auth.example/authorize",
    token_url="https://auth.example/token",
    redirect_uri="http://localhost:53692/callback",
    scopes="read write",
    extra_authorize_params={"code": "true"},
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    monkeypatch.setattr(oauth, "TOKEN_STORE", path)
    return path


# --- pure helpers -----------------------------------------------------------


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = oauth.generate_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected


def test_build_authorize_url():
    url = oauth.build_authorize_url(CONFIG, "CHAL", state="VER")
    assert url.startswith("https://auth.example/authorize?")
    assert "client_id=cid" in url and "code_challenge=CHAL" in url and "state=VER" in url
    assert "code_challenge_method=S256" in url and "code=true" in url  # extra param merged


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


def test_store_roundtrip_and_clear(store):
    oauth.save_token("demo", {"type": "oauth", "access": "A"})
    assert oauth.read_token("demo")["access"] == "A"
    assert oauth.clear_token("demo") is True
    assert oauth.read_token("demo") is None
    assert oauth.clear_token("demo") is False


def test_valid_token_returned_without_refresh(store):
    oauth.save_token("demo", {"type": "oauth", "access": "good", "expires": time.time() * 1000 + 3_600_000})
    assert oauth.current_access_token(CONFIG) == "good"


def test_expired_token_is_refreshed_and_persisted(store, monkeypatch):
    oauth.save_token("demo", {"type": "oauth", "access": "old", "refresh": "R", "expires": time.time() * 1000 - 1000})

    def fake_post(config, body):
        assert body["grant_type"] == "refresh_token" and body["refresh_token"] == "R"
        return {"access_token": "new", "refresh_token": "R2", "expires_in": 3600}

    monkeypatch.setattr(oauth, "_post_token", fake_post)
    assert oauth.current_access_token(CONFIG) == "new"
    assert oauth.read_token("demo")["access"] == "new"


def test_no_token_returns_none(store):
    assert oauth.current_access_token(CONFIG) is None


# --- login ------------------------------------------------------------------


def test_manual_login_persists_token(store, monkeypatch):
    captured = {}
    real_pkce = oauth.generate_pkce

    def spy_pkce():
        v, c = real_pkce()
        captured["verifier"] = v
        return v, c

    monkeypatch.setattr(oauth, "generate_pkce", spy_pkce)
    monkeypatch.setattr(oauth, "_post_token", lambda config, body: {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})

    cred = oauth.login(
        CONFIG, manual=True, opener=lambda url: None,
        prompt=lambda _m: f"CODE#{captured['verifier']}", echo=lambda *a: None,
    )
    assert cred["access"] == "AT"
    assert oauth.read_token("demo")["access"] == "AT"


def test_login_state_mismatch_aborts(store, monkeypatch):
    monkeypatch.setattr(oauth, "_post_token", lambda config, body: {"access_token": "x", "expires_in": 1})
    with pytest.raises(oauth.ProviderError):
        oauth.login(CONFIG, manual=True, opener=lambda url: None,
                    prompt=lambda _m: "CODE#WRONG", echo=lambda *a: None)
