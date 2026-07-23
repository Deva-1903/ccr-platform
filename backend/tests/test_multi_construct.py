"""Multi-construct runs: one job scores N constructs on a single corpus pass
and reports how they interrelate (per-text score correlations).

Contract under test:
  * summary gains constructs[] + correlations{}; single-construct summaries
    keep the original flat shape (including when sent as a one-element list),
  * export columns are prefixed per construct ({slug}_sim_item_N,
    {slug}_ccr_score) with no ambiguous bare ccr_score,
  * metadata carries every construct snapshot under schema version 1.1,
  * the reproduction script reproduces ALL constructs and stays valid Python.
"""

import ast
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
    "5,Caring for others and protecting the vulnerable matters to me.\n"
)


def wait_for_job(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # lifespan seeds the construct library
        yield c


@pytest.fixture(scope="module")
def flow(client):
    project = client.post(
        "/api/projects", json={"name": "Multi", "description": "multi-construct e2e"}
    ).json()
    corpus = client.post(
        f"/api/projects/{project['id']}/corpora",
        files={"file": ("corpus.csv", io.BytesIO(CSV.encode()), "application/octet-stream")},
    ).json()
    constructs = client.get("/api/constructs").json()
    swls = next(c for c in constructs if c["name"] == "Satisfaction with Life")
    care = next(c for c in constructs if c["name"] == "Moral Foundations - Care")

    job = client.post(
        "/api/jobs",
        json={
            "project_id": project["id"],
            "corpus_id": corpus["id"],
            "construct_ids": [swls["id"], care["id"]],
            "text_column": "text",
            "model_name": "fake-deterministic",
        },
    ).json()
    job = wait_for_job(client, job["id"])
    return {"project": project, "corpus": corpus, "constructs": [swls, care], "job": job}


def test_multi_job_completes_and_lists_constructs(flow):
    job = flow["job"]
    assert job["status"] == "completed", job["error"]
    assert job["construct_ids"] == [c["id"] for c in flow["constructs"]]
    assert job["construct_names"] == ["Satisfaction with Life", "Moral Foundations - Care"]
    assert job["construct_name"] == "Satisfaction with Life"  # legacy field = first


def test_multi_summary_has_per_construct_stats_and_correlations(client, flow):
    body = client.get(f"/api/jobs/{flow['job']['id']}/results").json()
    summary = body["summary"]
    assert summary["n_docs"] == 5
    assert "score_mean" not in summary  # per-construct now, not flat

    blocks = summary["constructs"]
    assert [b["construct_name"] for b in blocks] == [
        "Satisfaction with Life", "Moral Foundations - Care",
    ]
    for b in blocks:
        assert {"score_mean", "score_sd", "histogram", "item_means",
                "top_docs", "bottom_docs", "column_prefix"} <= set(b)
        assert len(b["item_means"]) == b["n_items"]

    corr = summary["correlations"]
    assert corr["method"] == "pearson"
    assert corr["n_texts"] == 5
    assert corr["constructs"] == [b["construct_name"] for b in blocks]
    m = corr["matrix"]
    assert len(m) == 2 and len(m[0]) == 2
    assert m[0][0] == 1.0 and m[1][1] == 1.0
    assert m[0][1] == m[1][0]
    assert m[0][1] is None or -1.0 <= m[0][1] <= 1.0


def test_multi_export_columns_are_prefixed(client, flow):
    body = client.get(f"/api/jobs/{flow['job']['id']}/results").json()
    prefixes = [b["column_prefix"] for b in body["summary"]["constructs"]]
    assert len(set(prefixes)) == 2

    header = client.get(f"/api/jobs/{flow['job']['id']}/export").text.splitlines()[0].split(",")
    assert header[:2] == ["id", "text"]
    assert "ccr_score" not in header  # would be ambiguous with 2 constructs
    for prefix, construct in zip(prefixes, flow["constructs"]):
        assert f"{prefix}_ccr_score" in header
        n_sim = sum(1 for h in header if h.startswith(f"{prefix}_sim_item_"))
        assert n_sim == len(construct["items"])


def test_multi_metadata_versions_and_snapshots(client, flow):
    metadata = client.get(f"/api/jobs/{flow['job']['id']}/results").json()["metadata"]
    assert metadata["output_schema_version"] == "1.1"
    assert metadata["construct"] == "Satisfaction with Life + Moral Foundations - Care"
    assert "items_sha256_16" not in metadata  # ambiguous at top level; lives per construct
    blocks = metadata["constructs"]
    assert len(blocks) == 2
    for b in blocks:
        assert b["items_sha256_16"]
        assert b["snapshot"]["item_hash"] and b["snapshot"]["items"]
        assert f"{b['column_prefix']}_ccr_score" in metadata["output_schema"]
    assert metadata["correlations"]["matrix"][0][0] == 1.0
    assert metadata["n_items"] == sum(b["n_items"] for b in blocks)


def test_multi_script_reproduces_all_constructs(client, flow):
    job_id = flow["job"]["id"]
    script = client.get(f"/api/jobs/{job_id}/script").text
    ast.parse(script)  # must be valid offline Python
    assert "CONSTRUCTS" in script
    prefixes = [
        b["column_prefix"]
        for b in client.get(f"/api/jobs/{job_id}/results").json()["summary"]["constructs"]
    ]
    for prefix in prefixes:
        assert prefix in script
    # embeds the corpus once, not once per construct
    assert script.count("doc_emb = model.encode") == 1


def test_single_construct_via_list_keeps_flat_shape(client, flow):
    """The UI now always sends construct_ids; a one-element list must behave
    exactly like the original single-construct API (shape and schema 1.0)."""
    # Fresh upload: the flow corpus's file was deleted after its run
    # (anonymous retention), so it can't be re-run.
    corpus = client.post(
        f"/api/projects/{flow['project']['id']}/corpora",
        files={"file": ("again.csv", io.BytesIO(CSV.encode()), "application/octet-stream")},
    ).json()
    resp = client.post(
        "/api/jobs",
        json={
            "project_id": flow["project"]["id"],
            "corpus_id": corpus["id"],
            "construct_ids": [flow["constructs"][0]["id"]],
            "text_column": "text",
            "model_name": "fake-deterministic",
        },
    )
    assert resp.status_code == 201, resp.text
    job = wait_for_job(client, resp.json()["id"])
    assert job["status"] == "completed", job["error"]
    body = client.get(f"/api/jobs/{job['id']}/results").json()
    assert "constructs" not in body["summary"]
    assert "score_mean" in body["summary"]
    assert body["metadata"]["output_schema_version"] == "1.0"
    header = client.get(f"/api/jobs/{job['id']}/export").text.splitlines()[0].split(",")
    assert "ccr_score" in header and "sim_item_1" in header


def test_multi_validation_errors(client, flow):
    base = {
        "project_id": flow["project"]["id"],
        "corpus_id": flow["corpus"]["id"],
        "text_column": "text",
        "model_name": "fake-deterministic",
    }
    swls_id = flow["constructs"][0]["id"]

    resp = client.post("/api/jobs", json={**base, "construct_ids": []})
    assert resp.status_code == 400  # no construct at all

    resp = client.post("/api/jobs", json={**base, "construct_ids": [swls_id, swls_id]})
    assert resp.status_code == 400
    assert "Duplicate" in resp.json()["detail"]

    all_ids = [c["id"] for c in client.get("/api/constructs").json()][:11]
    resp = client.post("/api/jobs", json={**base, "construct_ids": all_ids})
    assert resp.status_code == 400
    assert "At most 10" in resp.json()["detail"]

    resp = client.post("/api/jobs", json={**base, "construct_ids": [swls_id, "nonexistent"]})
    assert resp.status_code == 404
