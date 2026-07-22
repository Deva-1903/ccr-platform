"""Accounts, sessions, and usage tiers.

Local email+password accounts - the "best cheap option available now" (Deva,
2026-07-11): zero external dependencies, zero cost, real password security via
stdlib scrypt. This deliberately does NOT implement email verification or
self-service password reset; at lab scale a reset is an admin action. The
managed-provider swap (Supabase: Google + email/password, design doc §8)
replaces token creation/verification here - get_current_user() stays the only
integration point the rest of the app knows about.

Sessions: HMAC-signed cookie carrying {uid, email, name}. Secret from
CCR_SESSION_SECRET (REQUIRED in production - random per process otherwise,
which signs everyone out on restart).

Anonymous usage tiers (PI decisions, 2026-07-10):
  * upload caps (bytes/rows),
  * run limit per day (signed cookie counter - a nudge toward accounts, not a
    security boundary; clearing cookies evades it and that is acceptable),
  * data removed after analysis (see retention.py).
Signed-in users: caps lifted, runs persist up to a saved-run cap.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timezone

from fastapi import Request

COOKIE_NAME = "ccr_session"
RUNS_COOKIE_NAME = "ccr_runs"
_SECRET = (os.environ.get("CCR_SESSION_SECRET") or secrets.token_hex(32)).encode()

# Headroom for 200 rows of long documents (200 x 8 KB transcripts ~ 1.6 MB sat
# uncomfortably close to the old 2 MB). Still a cheap pre-parse shield on the
# unauthenticated path: the 200-row cap below is what actually binds.
ANON_MAX_BYTES_DEFAULT = 5 * 1024 * 1024
ANON_MAX_ROWS_DEFAULT = 200  # PI decision 2026-07-14 (was 500)
ANON_MAX_RUNS_PER_DAY_DEFAULT = 3
USER_MAX_SAVED_RUNS_DEFAULT = 15
ANON_TTL_HOURS_DEFAULT = 0  # 0 = purge disabled (local dev); deployments set 24

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8


# ------------------------------------------------------------- env knobs
def anon_max_bytes() -> int:
    return int(os.environ.get("CCR_ANON_MAX_BYTES", ANON_MAX_BYTES_DEFAULT))


def anon_max_rows() -> int:
    return int(os.environ.get("CCR_ANON_MAX_ROWS", ANON_MAX_ROWS_DEFAULT))


def anon_max_runs_per_day() -> int:
    return int(os.environ.get("CCR_ANON_MAX_RUNS_PER_DAY", ANON_MAX_RUNS_PER_DAY_DEFAULT))


def user_max_saved_runs() -> int:
    return int(os.environ.get("CCR_USER_MAX_SAVED_RUNS", USER_MAX_SAVED_RUNS_DEFAULT))


def anon_ttl_hours() -> int:
    return int(os.environ.get("CCR_ANON_TTL_HOURS", ANON_TTL_HOURS_DEFAULT))


def cookies_secure() -> bool:
    """Set CCR_COOKIE_SECURE=1 behind HTTPS in production."""
    return os.environ.get("CCR_COOKIE_SECURE") == "1"


def admin_emails() -> set[str]:
    """Comma-separated allowlist; env-granted, so it bootstraps the first
    admin and can never be locked out by DB state. See roles below for the
    DB-granted staff tiers (PI decision 2026-07-22)."""
    raw = os.environ.get("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin(email: str | None) -> bool:
    return bool(email) and email.strip().lower() in admin_emails()


# ------------------------------------------------------------- user roles
# Four tiers (PI decision 2026-07-22): pi | maintainer | lab | external.
#   * external   - default on signup; saved-run cap applies.
#   * lab        - lab members: unlimited saved runs.
#   * maintainer - lab privileges + the /admin operational surface
#                  (user management for lab/external, resets, requeue,
#                  verification queue, invites).
#   * pi         - maintainer surface + escalation rights: grant/revoke
#                  staff roles and act on staff accounts. The app is
#                  self-governing; ADMIN_EMAILS is bootstrap + break-glass
#                  only (seed the first PI, recover a locked-out lab).
# Escalation therefore requires pi-or-env-admin (admin.py guards), so a
# maintainer - or a compromised maintainer session - cannot mint staff.
ROLES = ("external", "lab", "maintainer", "pi")
UNLIMITED_ROLES = frozenset({"lab", "maintainer", "pi"})
STAFF_ROLES = frozenset({"maintainer", "pi"})
INVITABLE_ROLES = frozenset({"external", "lab"})  # staff is granted, never invited


def normalize_role(role: str | None) -> str:
    """Map stored roles to the current scheme ('member' predates 'external')."""
    role = (role or "").strip().lower()
    if role == "member":
        return "external"
    return role if role in ROLES else "external"


def role_unlimited(role: str | None) -> bool:
    """Lab members and above: no saved-run cap."""
    return normalize_role(role) in UNLIMITED_ROLES


def role_is_staff(role: str | None) -> bool:
    return normalize_role(role) in STAFF_ROLES


# ---------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=64)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1, dklen=64
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip().lower()))


# ------------------------------------------------- signed cookie payloads
def _sign(payload: bytes) -> str:
    return hmac.new(_SECRET, payload, hashlib.sha256).hexdigest()


def sign_payload(data: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    return f"{payload}.{_sign(payload.encode())}"


def verify_payload(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    payload, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(payload.encode())):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# ------------------------------------------------------------- sessions
def create_session_token(user_id: str, email: str, name: str) -> str:
    return sign_payload({"uid": user_id, "email": email, "name": name})


def get_current_user(request: Request) -> dict | None:
    """THE auth integration point (design doc §8). A managed provider (Supabase)
    replaces this body with provider-session verification; callers only ever see
    {"id", "email", "name", "tier"} or None."""
    data = verify_payload(request.cookies.get(COOKIE_NAME))
    if not data or "uid" not in data:
        return None
    return {
        "id": data["uid"],
        "email": data.get("email", ""),
        "name": data.get("name", ""),
        # placeholder only - real role lives in the users table (queried per
        # request in main.py/admin.py so role changes apply without re-login)
        "tier": "external",
    }


# ------------------------------------------------------------ invite links
# Signed, expiring tokens the PI copies into Slack; whoever registers through
# one lands at the invited tier instead of external. The signature proves the
# token came from us; the invites TABLE (models.Invite, id = the token's jti)
# decides whether it is still live - so links can be revoked early and every
# redemption is traced to the link that granted it.
INVITE_TTL_DAYS_DEFAULT = 7


def invite_ttl_days() -> int:
    return int(os.environ.get("CCR_INVITE_TTL_DAYS", INVITE_TTL_DAYS_DEFAULT))


def create_invite_token(role: str, invited_by: str, jti: str) -> tuple[str, str]:
    """Returns (token, expires_at ISO date). Role must be invitable; jti is
    the Invite row id the token points back to."""
    from datetime import timedelta

    role = normalize_role(role)
    if role not in INVITABLE_ROLES:
        raise ValueError(f"Only these roles can be invited: {', '.join(sorted(INVITABLE_ROLES))}.")
    expires = (datetime.now(timezone.utc) + timedelta(days=invite_ttl_days())).date().isoformat()
    return sign_payload({"invite": role, "by": invited_by, "exp": expires, "jti": jti}), expires


def verify_invite_token(token: str | None) -> dict | None:
    """{'role', 'jti'} for a well-signed, unexpired invite token; None
    otherwise. Liveness (revocation) is the caller's DB check - signature
    and expiry alone do not make a token redeemable."""
    data = verify_payload(token)
    if not data or "invite" not in data:
        return None
    if str(data.get("exp", "")) < datetime.now(timezone.utc).date().isoformat():
        return None  # expired (dates are ISO, so string compare is correct)
    role = normalize_role(str(data["invite"]))
    if role not in INVITABLE_ROLES:
        return None
    return {"role": role, "jti": str(data.get("jti", ""))}


# ------------------------------------------- anonymous daily run counter
def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def runs_used_today(request: Request) -> int:
    data = verify_payload(request.cookies.get(RUNS_COOKIE_NAME))
    if not data or data.get("d") != _today():
        return 0  # missing, tampered, or from a previous day - counter resets
    try:
        return max(0, int(data.get("n", 0)))
    except (TypeError, ValueError):
        return 0


def run_counter_token(count: int) -> str:
    return sign_payload({"d": _today(), "n": int(count)})
