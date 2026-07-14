"""Sign-in tiers (anonymous caps lift on sign-in) and project lifecycle
(archive is reversible; delete cascades to files and rows)."""

import io
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


def upload(client, project_id, name, payload: bytes):
    return client.post(
        f"/api/projects/{project_id}/corpora",
        files={"file": (name, io.BytesIO(payload), "text/csv")},
    )


def wait_for_job(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.05)
    raise TimeoutError(job_id)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def csv_rows(n: int) -> bytes:
    return ("text\n" + "\n".join(f"sample sentence number {i} here" for i in range(n))).encode()


# ------------------------------------------------------------------- tiers
def test_anonymous_row_cap_and_signin_lifts_it(client, monkeypatch):
    monkeypatch.setenv("CCR_ANON_MAX_ROWS", "5")
    project = client.post("/api/projects", json={"name": "Tiers"}).json()

    me = client.get("/api/auth/me").json()
    assert me["signed_in"] is False and me["limits"]["max_rows"] == 5

    resp = upload(client, project["id"], "big.csv", csv_rows(10))
    assert resp.status_code == 400
    assert "Sign in" in resp.json()["detail"]

    resp = client.post(
        "/api/auth/register",
        json={"email": "deva@test.edu", "password": "password123", "name": "Deva"},
    )
    assert resp.status_code == 201
    me = client.get("/api/auth/me").json()
    assert me["signed_in"] is True and me["name"] == "Deva"

    resp = upload(client, project["id"], "big.csv", csv_rows(10))
    assert resp.status_code == 201, resp.json()

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json()["signed_in"] is False


def test_anonymous_size_cap(client, monkeypatch):
    monkeypatch.setenv("CCR_ANON_MAX_BYTES", "200")
    project = client.post("/api/projects", json={"name": "SizeCap"}).json()
    resp = upload(client, project["id"], "big.csv", csv_rows(50))
    assert resp.status_code == 413
    assert "Sign in" in resp.json()["detail"]


def test_tampered_session_cookie_is_anonymous(client):
    client.cookies.set("ccr_session", "aGFja2Vy.badsignature")
    assert client.get("/api/auth/me").json()["signed_in"] is False


# --------------------------------------------------------------- lifecycle
def test_archive_toggle_is_reversible(client):
    project = client.post("/api/projects", json={"name": "Archivable"}).json()
    assert project["archived"] is False

    patched = client.patch(f"/api/projects/{project['id']}", json={"archived": True}).json()
    assert patched["archived"] is True
    listed = next(p for p in client.get("/api/projects").json() if p["id"] == project["id"])
    assert listed["archived"] is True

    patched = client.patch(f"/api/projects/{project['id']}", json={"archived": False}).json()
    assert patched["archived"] is False


def test_delete_cascades_rows_and_files(client):
    project = client.post("/api/projects", json={"name": "Doomed"}).json()
    corpus = upload(client, project["id"], "corpus.csv", csv_rows(6)).json()

    constructs = client.get("/api/constructs").json()
    swls = next(c for c in constructs if c["name"] == "Satisfaction with Life")
    job = client.post(
        "/api/jobs",
        json={
            "project_id": project["id"],
            "corpus_id": corpus["id"],
            "construct_id": swls["id"],
            "text_column": "text",
            "model_name": "fake-deterministic",
        },
    ).json()
    job = wait_for_job(client, job["id"])
    assert job["status"] == "completed"

    # capture file paths before deletion
    results = client.get(f"/api/jobs/{job['id']}/results")
    assert results.status_code == 200

    resp = client.delete(f"/api/projects/{project['id']}")
    assert resp.status_code == 204

    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert all(p["id"] != project["id"] for p in client.get("/api/projects").json())
    # corpora listing for the deleted project 404s
    assert client.get(f"/api/projects/{project['id']}/corpora").status_code == 404


def test_delete_removes_files_on_disk(client, tmp_path):
    import os

    data_dir = Path(os.environ["CCR_DATA_DIR"])
    project = client.post("/api/projects", json={"name": "FileCheck"}).json()
    before = set((data_dir / "corpora").glob("*"))
    upload(client, project["id"], "corpus.csv", csv_rows(6))
    created = set((data_dir / "corpora").glob("*")) - before
    assert len(created) == 1

    client.delete(f"/api/projects/{project['id']}")
    assert not created.pop().exists()
