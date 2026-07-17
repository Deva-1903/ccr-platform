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
def test_verification_queue_marks_verified(client):
    sign_in_as(client, ADMIN_EMAIL, "Admin")
    queue = client.get("/api/admin/constructs?status=needs_verification").json()
    assert len(queue) > 0
    target = queue[0]

    resp = client.post(
        f"/api/admin/constructs/{target['id']}/verification", json={"status": "verified"}
    )
    assert resp.status_code == 200 and resp.json()["verification_status"] == "verified"

    remaining = client.get("/api/admin/constructs?status=needs_verification").json()
    assert all(c["id"] != target["id"] for c in remaining)
    # visible to regular users too (flag disappears in the picker/details)
    pub = next(c for c in client.get("/api/constructs").json() if c["id"] == target["id"])
    assert pub["verification_status"] == "verified"
