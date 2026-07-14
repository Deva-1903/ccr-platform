"""Accounts (register/login), anonymous run limits, retention (delete-after-
analysis + TTL purge), saved-run cap, ownership, and construct file upload."""

import io
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def csv_rows(n: int) -> bytes:
    return ("text\n" + "\n".join(f"sample sentence number {i} here" for i in range(n))).encode()


def upload(client, project_id, name, payload: bytes):
    return client.post(
        f"/api/projects/{project_id}/corpora",
        files={"file": (name, io.BytesIO(payload), "text/csv")},
    )


def register(client, email="user@test.edu", name="Test User"):
    resp = client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": name}
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()


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


def any_construct(client):
    return client.get("/api/constructs").json()[0]


# ---------------------------------------------------------------- accounts
def test_register_login_logout_roundtrip(client):
    register(client, "roundtrip@test.edu", "Rounder")
    me = client.get("/api/auth/me").json()
    assert me["signed_in"] and me["email"] == "roundtrip@test.edu"
    assert me["usage"]["max_saved_runs"] > 0

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json()["signed_in"] is False

    resp = client.post(
        "/api/auth/login", json={"email": "ROUNDTRIP@test.edu", "password": "password123"}
    )
    assert resp.status_code == 200  # email is case-insensitive
    assert client.get("/api/auth/me").json()["signed_in"] is True


def test_wrong_password_and_duplicate_email(client):
    register(client, "dupe@test.edu")
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/login", json={"email": "dupe@test.edu", "password": "wrongpass1"})
    assert resp.status_code == 401
    resp = client.post(
        "/api/auth/register", json={"email": "dupe@test.edu", "password": "password123", "name": "X"}
    )
    assert resp.status_code == 409


def test_register_validation(client):
    resp = client.post(
        "/api/auth/register", json={"email": "not-an-email", "password": "password123", "name": "X"}
    )
    assert resp.status_code == 400


# ------------------------------------------------------ anonymous run limit
def test_anonymous_daily_run_limit(client, monkeypatch):
    monkeypatch.setenv("CCR_ANON_MAX_RUNS_PER_DAY", "2")
    project = client.post("/api/projects", json={"name": "Limited"}).json()
    construct = any_construct(client)

    for i in range(2):
        corpus = upload(client, project["id"], f"c{i}.csv", csv_rows(5)).json()
        resp = run_job(client, project["id"], corpus["id"], construct["id"])
        assert resp.status_code == 201, resp.json()
        wait_for_job(client, resp.json()["id"])

    me = client.get("/api/auth/me").json()
    assert me["usage"]["runs_used_today"] == 2

    corpus = upload(client, project["id"], "c3.csv", csv_rows(5)).json()
    resp = run_job(client, project["id"], corpus["id"], construct["id"])
    assert resp.status_code == 429
    assert "Sign in" in resp.json()["detail"]


def test_signed_in_users_bypass_run_limit(client, monkeypatch):
    monkeypatch.setenv("CCR_ANON_MAX_RUNS_PER_DAY", "1")
    register(client, "runner@test.edu")
    project = client.post("/api/projects", json={"name": "Unlimited"}).json()
    corpus = upload(client, project["id"], "c.csv", csv_rows(5)).json()
    construct = any_construct(client)
    for _ in range(3):
        resp = run_job(client, project["id"], corpus["id"], construct["id"])
        assert resp.status_code == 201, resp.json()
        wait_for_job(client, resp.json()["id"])


# ----------------------------------------------------------------- retention
def test_anonymous_corpus_removed_after_run_and_rerun_gets_410(client):
    from pathlib import Path

    project = client.post("/api/projects", json={"name": "Ephemeral"}).json()
    corpus = upload(client, project["id"], "c.csv", csv_rows(5)).json()
    construct = any_construct(client)

    resp = run_job(client, project["id"], corpus["id"], construct["id"])
    job = wait_for_job(client, resp.json()["id"])
    assert job["status"] == "completed"

    results = client.get(f"/api/jobs/{job['id']}/results").json()
    codes = [w["code"] for w in results["summary"]["warnings"]]
    assert "ANONYMOUS_DATA_REMOVED" in codes
    assert results["metadata"]["anonymous_corpus_removed"] is True
    # results are still downloadable; the raw upload is gone
    assert client.get(f"/api/jobs/{job['id']}/export").status_code == 200

    resp = run_job(client, project["id"], corpus["id"], construct["id"])
    assert resp.status_code == 410


def test_signed_in_corpus_survives_run(client):
    register(client, "keeper@test.edu")
    project = client.post("/api/projects", json={"name": "Kept"}).json()
    corpus = upload(client, project["id"], "c.csv", csv_rows(5)).json()
    construct = any_construct(client)

    resp = run_job(client, project["id"], corpus["id"], construct["id"])
    job = wait_for_job(client, resp.json()["id"])
    assert job["status"] == "completed"
    codes = [w["code"] for w in client.get(f"/api/jobs/{job['id']}/results").json()["summary"]["warnings"]]
    assert "ANONYMOUS_DATA_REMOVED" not in codes

    # re-running the same corpus works: the file is still there
    resp = run_job(client, project["id"], corpus["id"], construct["id"])
    assert resp.status_code == 201


def test_ttl_purge_removes_only_expired_anonymous_projects(client, monkeypatch):
    from app.db import SessionLocal
    from app.models import Project
    from app.retention import purge_expired_anonymous

    monkeypatch.setenv("CCR_ANON_TTL_HOURS", "24")
    old_anon = client.post("/api/projects", json={"name": "OldAnon"}).json()
    fresh_anon = client.post("/api/projects", json={"name": "FreshAnon"}).json()
    register(client, "owner@test.edu")
    owned = client.post("/api/projects", json={"name": "OwnedOld"}).json()

    db = SessionLocal()
    try:
        db.get(Project, old_anon["id"]).created_at = "2020-01-01T00:00:00+00:00"
        db.get(Project, owned["id"]).created_at = "2020-01-01T00:00:00+00:00"
        db.commit()
        purged = purge_expired_anonymous(db)
        assert purged == 1
        assert db.get(Project, old_anon["id"]) is None
        assert db.get(Project, fresh_anon["id"]) is not None
        assert db.get(Project, owned["id"]) is not None  # owned data never TTL-purged
    finally:
        db.close()


# ------------------------------------------------------------ saved-run cap
def test_saved_run_cap_for_signed_in_users(client, monkeypatch):
    monkeypatch.setenv("CCR_USER_MAX_SAVED_RUNS", "2")
    register(client, "capped@test.edu")
    project = client.post("/api/projects", json={"name": "Capped"}).json()
    corpus = upload(client, project["id"], "c.csv", csv_rows(5)).json()
    construct = any_construct(client)

    for _ in range(2):
        resp = run_job(client, project["id"], corpus["id"], construct["id"])
        assert resp.status_code == 201
        wait_for_job(client, resp.json()["id"])

    resp = run_job(client, project["id"], corpus["id"], construct["id"])
    assert resp.status_code == 409
    assert "saved runs" in resp.json()["detail"]


# ---------------------------------------------------------------- ownership
def test_owned_projects_invisible_and_untouchable_to_others(client):
    register(client, "alice@test.edu", "Alice")
    owned = client.post("/api/projects", json={"name": "AlicePrivate"}).json()
    client.post("/api/auth/logout")

    ids = [p["id"] for p in client.get("/api/projects").json()]
    assert owned["id"] not in ids  # invisible to anonymous viewers
    assert client.patch(f"/api/projects/{owned['id']}", json={"archived": True}).status_code == 403
    assert client.delete(f"/api/projects/{owned['id']}").status_code == 403

    register(client, "bob@test.edu", "Bob")
    assert client.patch(f"/api/projects/{owned['id']}", json={"archived": True}).status_code == 403


# ------------------------------------------------- construct file upload
def test_parse_construct_file_with_reverse_column(client):
    csv = "item,reverse\nI am satisfied with my life.,0\nI rarely feel content. ,1\n,\nI am satisfied with my life.,0\n"
    resp = client.post(
        "/api/constructs/parse-file",
        files={"file": ("swls_short.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["items"] == [
        {"text": "I am satisfied with my life.", "reverse_scored": False},
        {"text": "I rarely feel content.", "reverse_scored": True},
    ]
    assert any("blank" in w for w in body["warnings"])
    assert any("duplicate" in w for w in body["warnings"])
    assert body["suggested_name"] == "Swls Short"


def test_parse_construct_file_with_r_marker_single_column(client):
    csv = "text\nLife feels meaningful to me\nNothing I do matters (R)\n"
    resp = client.post(
        "/api/constructs/parse-file",
        files={"file": ("meaning.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    body = resp.json()
    assert body["items"][1] == {"text": "Nothing I do matters", "reverse_scored": True}


def test_parse_construct_file_rejects_bad_type_and_empty(client):
    resp = client.post(
        "/api/constructs/parse-file",
        files={"file": ("items.pdf", io.BytesIO(b"x"), "application/pdf")},
    )
    assert resp.status_code == 400
    resp = client.post(
        "/api/constructs/parse-file",
        files={"file": ("empty.csv", io.BytesIO(b"item\n"), "text/csv")},
    )
    assert resp.status_code == 400


# ------------------------------------------------------- perf: dedup encode
def test_encode_unique_matches_full_encode_and_saves_calls():
    import numpy as np

    from app.ccr import HashEmbeddingBackend, encode_unique

    class Counting(HashEmbeddingBackend):
        def __init__(self):
            super().__init__()
            self.n_encoded = 0

        def encode(self, texts, progress_cb=None):
            self.n_encoded += len(texts)
            return super().encode(texts, progress_cb)

    texts = ["alpha beta", "gamma delta", "alpha beta", "alpha beta", "gamma delta"]
    counting = Counting()
    deduped = encode_unique(counting, texts)
    assert counting.n_encoded == 2  # only unique texts hit the encoder
    full = HashEmbeddingBackend().encode(texts)
    assert np.allclose(deduped, full)  # bit-identical expansion


def test_created_construct_carries_reverse_flags_into_run_metadata(client):
    created = client.post(
        "/api/constructs",
        json={
            "name": "Flagged Scale",
            "items": ["good item", "bad item"],
            "reverse_scored": [False, True],
        },
    ).json()
    assert created["reverse_scored"] == [False, True]

    project = client.post("/api/projects", json={"name": "FlagRun"}).json()
    corpus = upload(client, project["id"], "c.csv", csv_rows(5)).json()
    resp = run_job(client, project["id"], corpus["id"], created["id"])
    job = wait_for_job(client, resp.json()["id"])
    snapshot = client.get(f"/api/jobs/{job['id']}/results").json()["metadata"]["construct_snapshot"]
    assert snapshot["items"][1]["reverse_scored"] is True
