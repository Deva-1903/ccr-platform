"""Google sign-in (Supabase PKCE): feature flag, redirect flow, callback
find-or-create, and password-login guard for Google-only accounts. The
Supabase exchange itself is mocked - no network in tests."""

import pytest
from fastapi.testclient import TestClient

from app import auth, auth_google
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def google_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fakeproj.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.setenv("CCR_APP_URL", "http://testserver")


def test_unconfigured_instance_hides_and_refuses_google(client):
    assert client.get("/api/auth/me").json().get("google_available") is False
    assert client.get("/api/auth/google/login", follow_redirects=False).status_code == 503


def test_login_redirects_to_supabase_with_pkce(client, google_env):
    me = client.get("/api/auth/me").json()
    assert me["google_available"] is True

    resp = client.get("/api/auth/google/login", follow_redirects=False)
    assert resp.status_code == 307
    loc = resp.headers["location"]
    assert loc.startswith("https://fakeproj.supabase.co/auth/v1/authorize?")
    assert "provider=google" in loc
    assert "code_challenge=" in loc and "code_challenge_method=s256" in loc
    assert "redirect_to=http%3A%2F%2Ftestserver%2Fapi%2Fauth%2Fgoogle%2Fcallback" in loc
    assert auth_google.VERIFIER_COOKIE in resp.cookies


def test_callback_creates_user_and_signs_in(client, google_env, monkeypatch):
    monkeypatch.setattr(
        auth_google, "exchange",
        lambda code, verifier: {"email": "pi@lab.edu", "name": "The PI"},
    )
    client.cookies.set(auth_google.VERIFIER_COOKIE, auth.sign_payload({"v": "verifier123"}))

    resp = client.get("/api/auth/google/callback?code=abc", follow_redirects=False)
    assert resp.status_code == 307 and resp.headers["location"] == "/"

    me = client.get("/api/auth/me").json()
    assert me["signed_in"] is True and me["email"] == "pi@lab.edu" and me["name"] == "The PI"

    # second sign-in reuses the same account (no duplicate users)
    client.cookies.set(auth_google.VERIFIER_COOKIE, auth.sign_payload({"v": "verifier456"}))
    client.get("/api/auth/google/callback?code=def", follow_redirects=False)
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        assert db.query(User).filter_by(email="pi@lab.edu").count() == 1
    finally:
        db.close()


def test_callback_without_verifier_fails_safely(client, google_env):
    resp = client.get("/api/auth/google/callback?code=abc", follow_redirects=False)
    assert resp.status_code == 307
    assert "auth_error=" in resp.headers["location"]


def test_google_only_account_cannot_password_login(client, google_env, monkeypatch):
    monkeypatch.setattr(
        auth_google, "exchange",
        lambda code, verifier: {"email": "gonly@lab.edu", "name": "G Only"},
    )
    client.cookies.set(auth_google.VERIFIER_COOKIE, auth.sign_payload({"v": "v1"}))
    client.get("/api/auth/google/callback?code=abc", follow_redirects=False)
    client.post("/api/auth/logout")

    resp = client.post(
        "/api/auth/login", json={"email": "gonly@lab.edu", "password": "password123"}
    )
    assert resp.status_code == 401
    assert "Google" in resp.json()["detail"]
