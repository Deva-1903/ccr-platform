"""Google sign-in via Supabase Auth (server-side PKCE flow).

Feature-flagged: everything here is inert until SUPABASE_URL and
SUPABASE_ANON_KEY are set, so local dev and tests run unchanged without any
Supabase project. When configured, the flow is:

  1. GET /api/auth/google/login   -> redirect to Supabase's Google authorize
     URL with a PKCE challenge; the verifier rides in a short-lived signed
     cookie (never stored server-side).
  2. Google -> Supabase -> GET /api/auth/google/callback?code=...
  3. The backend exchanges code+verifier for the Supabase user (stdlib
     urllib - no new dependencies), finds-or-creates a local User row by
     email, and issues OUR normal session cookie (auth.py).

Design consequence: Supabase verifies identity at sign-in time only; the
session, tiers, and ownership model are exactly the same as email/password
accounts. Google users have an empty password_hash and cannot password-login
(a clear message says to use Google). Because users are re-created on next
sign-in by email, an ephemeral-disk dev instance losing its SQLite file is a
nuisance, not a lockout.

No frontend SDK: the button is a plain link, keeping the react+react-dom-only
dependency rule intact.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

VERIFIER_COOKIE = "ccr_pkce"
VERIFIER_TTL_SECONDS = 600


def configured() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_ANON_KEY"))


def _supabase_url() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/")


def app_url() -> str:
    """Public base URL of THIS app (redirect target). Local default matches
    the dev server; deployments set CCR_APP_URL."""
    return os.environ.get("CCR_APP_URL", "http://127.0.0.1:8000").rstrip("/")


def begin() -> tuple[str, str]:
    """Return (authorize_url, code_verifier)."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    params = urllib.parse.urlencode(
        {
            "provider": "google",
            "redirect_to": f"{app_url()}/api/auth/google/callback",
            "code_challenge": challenge,
            "code_challenge_method": "s256",
        }
    )
    return f"{_supabase_url()}/auth/v1/authorize?{params}", verifier


def exchange(code: str, verifier: str) -> dict:
    """Exchange the PKCE code for the Supabase user. Returns {email, name}.
    Raises ValueError with a user-safe message on any failure."""
    body = json.dumps({"auth_code": code, "code_verifier": verifier}).encode()
    req = urllib.request.Request(
        f"{_supabase_url()}/auth/v1/token?grant_type=pkce",
        data=body,
        headers={
            "apikey": os.environ["SUPABASE_ANON_KEY"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise ValueError("Google sign-in could not be completed. Please try again.") from exc

    user = payload.get("user") or {}
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise ValueError("Google sign-in returned no email address.")
    meta = user.get("user_metadata") or {}
    name = (meta.get("full_name") or meta.get("name") or email.split("@")[0]).strip()
    return {"email": email, "name": name}
