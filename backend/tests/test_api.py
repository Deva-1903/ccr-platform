"""End-to-end API tests: project -> upload -> job -> results -> export.

Run against the fake embedding backend (model_name = 'fake-deterministic'),
exercising the full pipeline — tolerant upload parsing, the real job queue
(worker thread + polling), results summary, warnings, and export shape —
without ML dependencies.
"""

import io
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

CSV = (
    "id,text\n"
    "1,I am deeply satisfied with my life and grateful every day.\n"
    "2,The bus was late again this morning.\n"
    "3,My life is close to my ideal in most ways.\n"
    "4,We fixed the printer in the lab office.\n"
    "5,The bus was late again this morning.\n"  # duplicate -> warning
    "6,\n"  # empty text row -> dropped and reported
)


def wait_for_job(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")


def upload(client, project_id, name, payload: bytes):
    return client.post(
        f"/api/projects/{project_id}/corpora",
        files={"file": (name, io.BytesIO(payload), "application/octet-stream")},
    )


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # context manager triggers lifespan (seeds constructs)
        yield c


@pytest.fixture(scope="module")
def flow(client):
    """Run the whole happy path once; individual tests assert on stages."""
    project = client.post(
        "/api/projects", json={"name": "Demo", "description": "e2e test"}
    ).json()

    corpus = upload(client, project["id"], "corpus.csv", CSV.encode()).json()

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
    return {"project": project, "corpus": corpus, "construct": swls, "job": job}


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_seed_constructs_present(client):
    names = {c["name"] for c in client.get("/api/constructs").json()}
    assert "Satisfaction with Life" in names
    assert "Moral Foundations — Care" in names


def test_corpus_upload_parses_columns(flow):
    corpus = flow["corpus"]
    assert corpus["columns"] == ["id", "text"]
    assert corpus["n_rows"] == 6
    assert corpus["suggested_text_column"] == "text"
    assert corpus["parse_info"]["encoding"] == "utf-8-sig"


def test_job_completes(flow):
    assert flow["job"]["status"] == "completed", flow["job"]["error"]
    assert flow["job"]["progress"] == 1.0


def test_results_summary_and_warnings(client, flow):
    body = client.get(f"/api/jobs/{flow['job']['id']}/results").json()
    summary, metadata = body["summary"], body["metadata"]
    assert summary["n_docs"] == 5  # empty row dropped
    assert summary["n_dropped_empty"] == 1
    assert len(summary["item_means"]) == 5  # SWLS has 5 items
    assert any("duplicate" in w for w in summary["warnings"])
    assert any("empty" in w for w in summary["warnings"])
    # satisfaction-flavored texts should outrank the bus/printer rows
    top_texts = " ".join(d["text"] for d in summary["top_docs"][:2])
    assert "satisfied" in top_texts or "ideal" in top_texts
    assert metadata["construct"] == "Satisfaction with Life"
    assert metadata["model"] == "fake-deterministic"
    assert metadata["corpus_parse_info"]["format"] == "csv"


def test_export_csv_shape(client, flow):
    resp = client.get(f"/api/jobs/{flow['job']['id']}/export")
    assert resp.status_code == 200
    header = resp.text.splitlines()[0].split(",")
    assert header[:2] == ["id", "text"]
    assert "ccr_score" in header
    assert sum(1 for h in header if h.startswith("sim_item_")) == 5


# ---------------------------------------------------------- ingest tolerance
def test_latin1_encoded_csv(client, flow):
    payload = "id,text\n1,café société naïveté\n2,plain row\n".encode("latin-1")
    resp = upload(client, flow["project"]["id"], "latin.csv", payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["n_rows"] == 2
    assert body["parse_info"]["encoding"] in ("utf-8-sig", "latin-1")


def test_semicolon_delimited_csv(client, flow):
    payload = b"id;text\n1;first sentence here\n2;second sentence here\n"
    resp = upload(client, flow["project"]["id"], "semi.csv", payload)
    assert resp.status_code == 201
    assert resp.json()["columns"] == ["id", "text"]


def test_row_cap_rejected(client, flow, monkeypatch):
    monkeypatch.setenv("CCR_MAX_ROWS", "3")
    payload = b"text\n" + b"\n".join(b"row %d" % i for i in range(10))
    resp = upload(client, flow["project"]["id"], "big.csv", payload)
    assert resp.status_code == 400
    assert "row limit" in resp.json()["detail"] or "limit" in resp.json()["detail"]


def test_validation_errors(client, flow):
    # bad column
    resp = client.post(
        "/api/jobs",
        json={
            "project_id": flow["project"]["id"],
            "corpus_id": flow["corpus"]["id"],
            "construct_id": flow["construct"]["id"],
            "text_column": "nope",
            "model_name": "fake-deterministic",
        },
    )
    assert resp.status_code == 400
    # bad file type
    resp = upload(client, flow["project"]["id"], "evil.exe", b"x")
    assert resp.status_code == 400
