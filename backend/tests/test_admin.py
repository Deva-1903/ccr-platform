"""Admin surface: env-allowlist gate, roles + lab-tier cap bypass, password
reset, user deletion cascade, failed-run requeue, verification queue."""

import io
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

ADMIN_EMAIL = "admin@lab.test"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", f"{ADMIN_EMAIL}, other-admin@lab.test")
    with TestClient(app) as c:
        yield c


def register(client, email, name="User"):
    resp = client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": name}
    )
    assert resp.status_code == 201
    return resp.json()


def sign_in_as(client, email, name="User"):
    """Login-or-register: the test DB persists across tests in this module."""
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    if resp.status_code != 200:
        register(client, email, name)


def csv_rows(n: int) -> bytes:
    return ("text\n" + "\n".join(f"sample sentence number {i} here" for i in range(n))).encode()


def upload(client, project_id, name, payload):
    return client.post(
        f"/api/projects/{project_id}/corpora",
        files={"file": (name, io.BytesIO(payload), "text/csv")},
    )


def run_job(client, project_id, corpus_id, construct_id):
    return client.post(
        "/api/jobs",
        json={
            "project_id": project_id,
            "corpus_id": corpus_id,
            "construct_id": construct_id,
            "text_column": "text",
            "model_name": "fake-deterministic",
        },
    )


def wait_for_job(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.05)
    raise TimeoutError(job_id)


# ------------------------------------------------------------------ access
def test_admin_requires_allowlisted_signed_in_user(client):
    assert client.get("/api/admin/overview").status_code == 403  # anonymous

    register(client, "normal@lab.test")
    assert client.get("/api/admin/overview").status_code == 403  # signed in, not allowlisted
    me = client.get("/api/auth/me").json()
    assert me["is_admin"] is False
    client.post("/api/auth/logout")

    register(client, ADMIN_EMAIL, "Admin")
    me = client.get("/api/auth/me").json()
    assert me["is_admin"] is True
    resp = client.get("/api/admin/overview")
    assert resp.status_code == 200
    assert resp.json()["users"] >= 2


def test_admin_page_route_serves_ui(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ------------------------------------------------------ roles and lab tier
def test_lab_role_bypasses_saved_run_cap(client, monkeypatch):
    monkeypatch.setenv("CCR_USER_MAX_SAVED_RUNS", "1")
    register(client, "phd@lab.test", "PhD")
    project = client.post("/api/projects", json={"name": "LabTier"}).json()
    corpus = upload(client, project["id"], "c.csv", csv_rows(5)).json()
    construct = client.get("/api/constructs").json()[0]

    resp = run_job(client, project["id"], corpus["id"], construct["id"])
    assert resp.status_code == 201
    wait_for_job(client, resp.json()["id"])
    assert run_job(client, project["id"], corpus["id"], construct["id"]).status_code == 409

    phd_id = next(
        u["id"] for u in _as_admin(client).get("/api/admin/users").json()
        if u["email"] == "phd@lab.test"
    )
    resp = client.post(f"/api/admin/users/{phd_id}/role", json={"role": "lab"})
    assert resp.status_code == 200 and resp.json()["role"] == "lab"
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"email": "phd@lab.test", "password": "password123"})
    me = client.get("/api/auth/me").json()
    assert me["role"] == "lab" and me["usage"]["max_saved_runs"] is None
    resp = run_job(client, project["id"], corpus["id"], construct["id"])
    assert resp.status_code == 201  # cap no longer applies


def _as_admin(client):
    sign_in_as(client, ADMIN_EMAIL, "Admin")
    return client


def _user_id(client, email):
    return next(u["id"] for u in client.get("/api/admin/users").json() if u["email"] == email)


# ------------------------------------------- four tiers (PI decision 2026-07-22)
def test_staff_roles_get_admin_surface_and_unlimited_runs(client, monkeypatch):
    monkeypatch.setenv("CCR_USER_MAX_SAVED_RUNS", "1")
    register(client, "newpi@lab.test", "The PI")
    me = client.get("/api/auth/me").json()
    assert me["role"] == "external" and me["is_admin"] is False  # default tier
    assert me["usage"]["max_saved_runs"] == 1
    client.post("/api/auth/logout")

    _as_admin(client)
    for role in ("pi", "maintainer", "lab", "external"):  # all four grantable
        resp = client.post(f"/api/admin/users/{_user_id(client, 'newpi@lab.test')}/role",
                           json={"role": role})
        assert resp.status_code == 200 and resp.json()["role"] == role
    client.post(f"/api/admin/users/{_user_id(client, 'newpi@lab.test')}/role",
                json={"role": "pi"})
    assert client.post(f"/api/admin/users/{_user_id(client, 'newpi@lab.test')}/role",
                       json={"role": "owner"}).status_code == 400
    overview = client.get("/api/admin/overview").json()
    assert overview["users_by_role"]["pi"] >= 1
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"email": "newpi@lab.test", "password": "password123"})
    me = client.get("/api/auth/me").json()
    assert me["role"] == "pi"
    assert me["is_admin"] is True  # staff role grants the admin surface...
    assert me["usage"]["max_saved_runs"] is None  # ...and unlimited saved runs
    assert client.get("/api/admin/overview").status_code == 200


def test_maintainer_cannot_escalate_or_touch_staff(client):
    _as_admin(client)
    for email, role in (("mnt@lab.test", "maintainer"), ("boss@lab.test", "pi"),
                        ("phd2@lab.test", "external")):
        sign_in_as(client, email)
        client.post("/api/auth/logout")
        _as_admin(client)
        client.post(f"/api/admin/users/{_user_id(client, email)}/role", json={"role": role})
    boss_id, phd_id = _user_id(client, "boss@lab.test"), _user_id(client, "phd2@lab.test")
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"email": "mnt@lab.test", "password": "password123"})
    # operational surface works, and lab/external grants are allowed...
    assert client.get("/api/admin/overview").status_code == 200
    assert client.post(f"/api/admin/users/{phd_id}/role",
                       json={"role": "lab"}).status_code == 200
    # ...but staff grants and any action on a staff account are env-admin only
    assert client.post(f"/api/admin/users/{phd_id}/role",
                       json={"role": "maintainer"}).status_code == 403
    assert client.post(f"/api/admin/users/{boss_id}/role",
                       json={"role": "external"}).status_code == 403
    assert client.post(f"/api/admin/users/{boss_id}/reset-password").status_code == 403
    assert client.delete(f"/api/admin/users/{boss_id}").status_code == 403
    client.post("/api/auth/logout")

    _as_admin(client)  # env admin CAN demote a staff account
    assert client.post(f"/api/admin/users/{boss_id}/role",
                       json={"role": "lab"}).status_code == 200


# --------------------------------------------------------- reset + delete
def test_password_reset_issues_working_temp_password(client):
    register(client, "forgetful@lab.test")
    sign_in_as(client, ADMIN_EMAIL, "Admin")

    uid = next(
        u["id"] for u in client.get("/api/admin/users").json()
        if u["email"] == "forgetful@lab.test"
    )
    temp = client.post(f"/api/admin/users/{uid}/reset-password").json()["temporary_password"]
    client.post("/api/auth/logout")

    bad = client.post(
        "/api/auth/login", json={"email": "forgetful@lab.test", "password": "password123"}
    )
    assert bad.status_code == 401  # old password dead
    good = client.post(
        "/api/auth/login", json={"email": "forgetful@lab.test", "password": temp}
    )
    assert good.status_code == 200


def test_password_reset_refused_for_google_account(client, monkeypatch):
    from app import auth_google
    monkeypatch.setattr(
        auth_google, "exchange",
        lambda code, verifier: {"email": "googler@lab.test", "name": "Googler"},
    )
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "k")
    from app import auth
    client.cookies.set(auth_google.VERIFIER_COOKIE, auth.sign_payload({"v": "v"}))
    client.get("/api/auth/google/callback?code=c", follow_redirects=False)
    client.post("/api/auth/logout")

    sign_in_as(client, ADMIN_EMAIL, "Admin")
    uid = next(
        u["id"] for u in client.get("/api/admin/users").json()
        if u["email"] == "googler@lab.test"
    )
    assert any(
        u["email"] == "googler@lab.test" and u["google_only"]
        for u in client.get("/api/admin/users").json()
    )
    resp = client.post(f"/api/admin/users/{uid}/reset-password")
    assert resp.status_code == 400 and "Google" in resp.json()["detail"]


def test_delete_user_cascades_and_protects_self(client):
    register(client, "doomed@lab.test")
    project = client.post("/api/projects", json={"name": "DoomedData"}).json()
    upload(client, project["id"], "c.csv", csv_rows(5))
    client.post("/api/auth/logout")

    sign_in_as(client, ADMIN_EMAIL, "Admin")
    users = client.get("/api/admin/users").json()
    doomed_id = next(u["id"] for u in users if u["email"] == "doomed@lab.test")
    my_id = next(u["id"] for u in users if u["email"] == ADMIN_EMAIL)

    assert client.delete(f"/api/admin/users/{my_id}").status_code == 400  # self-protect
    assert client.delete(f"/api/admin/users/{doomed_id}").status_code == 204
    assert all(
        u["email"] != "doomed@lab.test" for u in client.get("/api/admin/users").json()
    )
    assert client.get(f"/api/projects/{project['id']}/corpora").status_code in (403, 404)


# ------------------------------------------------------------ failed runs
def test_failed_job_requeue(client, monkeypatch):
    sign_in_as(client, ADMIN_EMAIL, "Admin")
    project = client.post("/api/projects", json={"name": "FailThenFix"}).json()
    corpus = upload(client, project["id"], "c.csv", csv_rows(5)).json()
    construct = client.get("/api/constructs").json()[0]

    # Force a failure: point the job at a column that exists in the DB row but
    # sabotage the stored file? Simpler: monkeypatch the engine to raise once.
    from app import jobs as jobs_module

    original = jobs_module.run_ccr
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic failure for admin requeue test")
        return original(*args, **kwargs)

    monkeypatch.setattr(jobs_module, "run_ccr", flaky)

    job = run_job(client, project["id"], corpus["id"], construct["id"]).json()
    assert wait_for_job(client, job["id"])["status"] == "failed"

    failed = client.get("/api/admin/jobs/failed").json()
    entry = next(f for f in failed if f["id"] == job["id"])
    assert entry["corpus_file_available"] is True
    assert "synthetic failure" in entry["error_tail"]

    assert client.post(f"/api/admin/jobs/{job['id']}/requeue").status_code == 200
    assert wait_for_job(client, job["id"])["status"] == "completed"


# ------------------------------------------------------------ verification
def _make_role(client, email, role):
    """Register (if needed) and set a role, as the env admin; leaves the
    client signed in as that user."""
    sign_in_as(client, email)
    client.post("/api/auth/logout")
    _as_admin(client)
    resp = client.post(f"/api/admin/users/{_user_id(client, email)}/role", json={"role": role})
    assert resp.status_code == 200, resp.json()
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": email, "password": "password123"})


def test_verification_is_the_maintainers_job(client):
    """PI decision 2026-07-22: maintainers verify; PI/admin see the queue
    read-only (the trail then names the responsible RA)."""
    sign_in_as(client, ADMIN_EMAIL, "Admin")
    queue = client.get("/api/admin/constructs?status=needs_verification").json()
    assert len(queue) > 0
    target = queue[0]

    # env admin: queue visible, verification action refused
    resp = client.post(
        f"/api/admin/constructs/{target['id']}/verification", json={"status": "verified"}
    )
    assert resp.status_code == 403 and "maintainer" in resp.json()["detail"]

    _make_role(client, "ra@lab.test", "maintainer")
    resp = client.post(
        f"/api/admin/constructs/{target['id']}/verification", json={"status": "verified"}
    )
    assert resp.status_code == 200 and resp.json()["verification_status"] == "verified"

    remaining = client.get("/api/admin/constructs?status=needs_verification").json()
    assert all(c["id"] != target["id"] for c in remaining)
    # visible to regular users too (flag disappears in the picker/details)
    pub = next(c for c in client.get("/api/constructs").json() if c["id"] == target["id"])
    assert pub["verification_status"] == "verified"


# ------------------------------------- pre-login access + audit (PI email 2026-07-22)
def test_preassigned_role_lands_on_first_signin(client):
    """The Dr. Chen scenario: full credentials bound to an email before the
    account exists; first sign-in (password or Google) claims them."""
    _as_admin(client)
    resp = client.post(
        "/api/admin/role-assignments",
        json={"email": "collaborator@other-lab.edu", "role": "maintainer"},
    )
    assert resp.status_code == 201
    pending = client.get("/api/admin/role-assignments").json()
    entry = next(a for a in pending if a["email"] == "collaborator@other-lab.edu")
    assert entry["role"] == "maintainer" and entry["claimed_at"] is None
    client.post("/api/auth/logout")

    register(client, "collaborator@other-lab.edu", "Dr. Chen")
    me = client.get("/api/auth/me").json()
    assert me["role"] == "maintainer" and me["is_admin"] is True
    assert me["usage"]["max_saved_runs"] is None
    client.post("/api/auth/logout")

    _as_admin(client)
    claimed = next(
        a for a in client.get("/api/admin/role-assignments").json()
        if a["email"] == "collaborator@other-lab.edu"
    )
    assert claimed["claimed_at"] is not None
    # existing accounts are managed in the Users table, not via pre-assignment
    resp = client.post(
        "/api/admin/role-assignments",
        json={"email": "collaborator@other-lab.edu", "role": "lab"},
    )
    assert resp.status_code == 409


def test_maintainer_cannot_preassign_staff(client):
    _make_role(client, "mnt3@lab.test", "maintainer")
    assert client.post(
        "/api/admin/role-assignments",
        json={"email": "someone@new.edu", "role": "pi"},
    ).status_code == 403
    assert client.post(
        "/api/admin/role-assignments",
        json={"email": "someone@new.edu", "role": "lab"},
    ).status_code == 201


def test_invite_link_grants_role_on_register(client, monkeypatch):
    _as_admin(client)
    invite = client.post("/api/admin/invites", json={"role": "lab"}).json()
    assert invite["role"] == "lab" and invite["token"] and invite["status"] == "active"
    # staff can never be invited by bearer link
    assert client.post("/api/admin/invites", json={"role": "maintainer"}).status_code == 400
    client.post("/api/auth/logout")

    resp = client.post("/api/auth/register", json={
        "email": "invited@lab.test", "password": "password123",
        "name": "Invited", "invite_token": invite["token"],
    })
    assert resp.status_code == 201
    me = client.get("/api/auth/me").json()
    assert me["role"] == "lab" and me["usage"]["max_saved_runs"] is None
    client.post("/api/auth/logout")

    # who used the link is visible on the invite row
    _as_admin(client)
    row = next(i for i in client.get("/api/admin/invites").json() if i["id"] == invite["id"])
    assert [r["email"] for r in row["redemptions"]] == ["invited@lab.test"]
    client.post("/api/auth/logout")

    # dead/garbage tokens refuse registration instead of silently demoting
    resp = client.post("/api/auth/register", json={
        "email": "invited2@lab.test", "password": "password123",
        "name": "Invited2", "invite_token": "garbage.token",
    })
    assert resp.status_code == 400 and "invite" in resp.json()["detail"].lower()

    monkeypatch.setenv("CCR_INVITE_TTL_DAYS", "-1")  # mint an already-expired invite
    _as_admin(client)
    expired = client.post("/api/admin/invites", json={"role": "lab"}).json()
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/register", json={
        "email": "invited3@lab.test", "password": "password123",
        "name": "Invited3", "invite_token": expired["token"],
    })
    assert resp.status_code == 400


def test_revoked_invite_stops_working(client):
    _as_admin(client)
    invite = client.post("/api/admin/invites", json={"role": "lab"}).json()
    assert client.delete(f"/api/admin/invites/{invite['id']}").status_code == 204
    row = next(i for i in client.get("/api/admin/invites").json() if i["id"] == invite["id"])
    assert row["status"] == "revoked" and row["token"] == ""  # dead links aren't re-copyable
    client.post("/api/auth/logout")

    resp = client.post("/api/auth/register", json={
        "email": "late@lab.test", "password": "password123",
        "name": "Late", "invite_token": invite["token"],
    })
    assert resp.status_code == 400 and "revoked" in resp.json()["detail"]


def test_audit_trail_records_and_is_pi_only(client):
    _as_admin(client)
    audit = client.get("/api/admin/audit")
    assert audit.status_code == 200
    actions = {(a["action"], a["target"]) for a in audit.json()}
    assert ("role_preassigned", "collaborator@other-lab.edu") in actions
    assert ("role_claimed", "collaborator@other-lab.edu") in actions
    assert ("invite_redeemed", "invited@lab.test") in actions
    assert any(a[0] == "set_verification" for a in actions)
    client.post("/api/auth/logout")

    # maintainers work the cards but don't get top-down oversight
    client.post("/api/auth/login", json={"email": "mnt3@lab.test", "password": "password123"})
    assert client.get("/api/admin/audit").status_code == 403


def test_pi_role_holds_escalation_rights_and_no_self_change(client):
    _make_role(client, "pi2@lab.test", "pi")
    me = client.get("/api/auth/me").json()
    assert me["role"] == "pi" and me["is_admin"] is True

    sign_in_as(client, "newbie@lab.test")
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "pi2@lab.test", "password": "password123"})
    newbie_id = _user_id(client, "newbie@lab.test")
    # a PI-by-role can mint staff and see the audit trail - no env entry needed
    assert client.post(f"/api/admin/users/{newbie_id}/role",
                       json={"role": "maintainer"}).status_code == 200
    assert client.get("/api/admin/audit").status_code == 200
    # but nobody, PI included, can change their own role
    my_id = _user_id(client, "pi2@lab.test")
    resp = client.post(f"/api/admin/users/{my_id}/role", json={"role": "external"})
    assert resp.status_code == 400 and "own role" in resp.json()["detail"]
