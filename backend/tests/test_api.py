"""End-to-end API tests: project -> upload -> job -> results -> export.

Run against the fake embedding backend (model_name = 'fake-deterministic'),
exercising the full pipeline - tolerant upload parsing, the real job queue
(worker thread + polling), results summary, warnings, and export shape -
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
    assert "Moral Foundations - Care" in names


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
    codes = {w["code"] for w in summary["warnings"]}  # structured objects (spec 0001)
    assert "DUPLICATE_TEXTS" in codes
    assert "EMPTY_ROWS_DROPPED" in codes
    assert all({"code", "severity", "message"} <= set(w) for w in summary["warnings"])
    # satisfaction-flavored texts should outrank the bus/printer rows
    top_texts = " ".join(d["text"] for d in summary["top_docs"][:2])
    assert "satisfied" in top_texts or "ideal" in top_texts
    assert metadata["construct"] == "Satisfaction with Life"
    assert metadata["model"] == "fake-deterministic"
    assert metadata["corpus_parse_info"]["format"] == "csv"
    # spec 0001/0004 metadata additions
    assert metadata["output_schema_version"] == "1.0"
    assert metadata["scoring"]["adjustment_strategy"] == "none"
    assert metadata["language"]["selected"] == "en"
    snapshot = metadata["construct_snapshot"]
    assert snapshot["construct_id"] == "satisfaction_with_life"
    assert snapshot["item_hash"] and len(snapshot["items"]) == 5
    assert "ccr_score" in metadata["output_schema"]


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
    # unknown model id (registry-validated now)
    resp = client.post(
        "/api/jobs",
        json={
            "project_id": flow["project"]["id"],
            "corpus_id": flow["corpus"]["id"],
            "construct_id": flow["construct"]["id"],
            "text_column": "text",
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",  # provider id, not registry id
        },
    )
    assert resp.status_code == 400


def test_projects_carry_activity_and_sort_by_it(client, flow):
    projects = client.get("/api/projects").json()
    demo = next(p for p in projects if p["id"] == flow["project"]["id"])
    assert demo["n_runs"] >= 1
    assert demo["last_activity_at"] >= demo["created_at"]
    # the project with runs sorts above a freshly created empty one from earlier tests
    order = [p["last_activity_at"] for p in projects]
    assert order == sorted(order, reverse=True)


# --------------------------------------------------- spec 0003: models API
def test_models_endpoint_from_registry(client):
    models = client.get("/api/models").json()
    ids = [m["id"] for m in models]
    assert "all-minilm-l6-v2" in ids and "e5-large-v2" in ids and "multilingual-e5-base" in ids
    defaults = [m for m in models if m["default"]]
    assert len(defaults) == 1 and defaults[0]["id"] == "all-minilm-l6-v2"
    assert client.get("/api/languages").json()[0] == "en"


# --------------------------------------------------- spec 0004: construct library
def test_constructs_carry_library_fields(client):
    swls = next(
        c for c in client.get("/api/constructs").json()
        if c["name"] == "Satisfaction with Life"
    )
    assert swls["verification_status"] == "needs_verification"
    assert swls["version"] == 1
    assert len(swls["item_hash"]) == 16
    assert swls["reverse_scored"] == [False] * 5


# --------------------------------------------------- spec 0001: language warnings
def test_language_uncertain_on_tiny_corpus(client, flow):
    body = client.get(f"/api/jobs/{flow['job']['id']}/results").json()
    codes = {w["code"] for w in body["summary"]["warnings"]}
    # 5-row corpus is far below the 20 detectable-row minimum
    assert "LANGUAGE_UNCERTAIN" in codes
    assert body["metadata"]["language"]["detected"] is None


def test_short_text_and_model_language_warnings(client, flow):
    csv = "text\n" + "\n".join(
        [f"esta es una frase de prueba número {i} para el corpus" for i in range(25)]
        + ["si", "no"]  # two very short rows
    )
    corpus = upload(client, flow["project"]["id"], "spanish.csv", csv.encode()).json()
    job = client.post(
        "/api/jobs",
        json={
            "project_id": flow["project"]["id"],
            "corpus_id": corpus["id"],
            "construct_id": flow["construct"]["id"],
            "text_column": "text",
            "model_name": "fake-deterministic",
            "language": "es",
        },
    ).json()
    job = wait_for_job(client, job["id"])
    assert job["status"] == "completed", job["error"]
    body = client.get(f"/api/jobs/{job['id']}/results").json()
    warnings = {w["code"]: w for w in body["summary"]["warnings"]}
    assert warnings["TEXT_TOO_SHORT"]["count"] == 2
    assert warnings["TEXT_TOO_SHORT"]["affected_rows_sample"]
    assert body["metadata"]["language"]["selected"] == "es"


# --------------------------------------------------- spec 0002: script export
def test_script_export_is_valid_offline_python(client, flow):
    import ast

    job_id = flow["job"]["id"]
    resp = client.get(f"/api/jobs/{job_id}/script")
    assert resp.status_code == 200
    source = resp.text
    tree = compile(source, "reproduce_analysis.py", "exec", ast.PyCF_ONLY_AST)
    # ITEMS must be a pure Python literal that *evaluates*, not just parses -
    # json.dumps once produced `true`/`false`, which compiles (bare identifiers)
    # but NameErrors at runtime. literal_eval rejects exactly that.
    items_node = next(
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and n.targets[0].id == "ITEMS"
    )
    items = ast.literal_eval(items_node)
    assert len(items) == 5  # SWLS
    assert all(isinstance(i["reverse_scored"], bool) for i in items)
    # embeds the construct items verbatim and never references the platform
    assert "In most ways my life is close to my ideal." in source
    assert "sim_item_" in source and "ccr_score" in source
    assert "127.0.0.1" not in source and "/api/" not in source


def test_script_export_instructions_match_download_names(client, flow):
    """The usage header must name the files exactly as they download (run-id
    suffix) and use the uploaded corpus as the example argument."""
    job_id = flow["job"]["id"]
    resp = client.get(f"/api/jobs/{job_id}/script")
    script_name = f"reproduce_analysis_{job_id[:8]}.py"
    assert f'filename="{script_name}"' in resp.headers["content-disposition"]
    assert f"python {script_name} corpus.csv" in resp.text  # uploaded CSV name

    reqs = client.get(f"/api/jobs/{job_id}/script-requirements")
    assert reqs.status_code == 200
    assert "==" in reqs.text  # pinned versions, not ranges
    reqs_name = f"requirements-repro_{job_id[:8]}.txt"
    assert f'filename="{reqs_name}"' in reqs.headers["content-disposition"]
    assert f"pip install -r {reqs_name}" in resp.text  # script points at reqs
    assert f"pip install -r {reqs_name}" in reqs.text  # reqs header self-refers


# ------------------------------------------- uploads must not clobber each other
def test_second_upload_does_not_clobber_first(client, flow):
    """Regression: corpus ids used to be read before INSERT (still None), so
    every upload stored to the same "None.csv" - a later upload silently
    replaced an earlier corpus's file, and runs analyzed the wrong dataset."""
    project = client.post("/api/projects", json={"name": "clobber-check"}).json()

    first = upload(client, project["id"], "first.csv",
                   b"text\nalpha one\nalpha two\nalpha three\n").json()
    second = upload(client, project["id"], "second.csv",
                    b"text\nbeta one\nbeta two\nbeta three\nbeta four\n").json()

    # Distinct stored files, both still present after the second upload.
    from pathlib import Path
    assert first["id"] and second["id"] and first["id"] != second["id"]
    paths = {
        c["filename"]: c for c in
        client.get(f"/api/projects/{project['id']}/corpora").json()
    }
    assert paths["first.csv"]["n_rows"] == 3 and paths["second.csv"]["n_rows"] == 4

    # Running the FIRST corpus must analyze the first corpus's rows.
    job = client.post("/api/jobs", json={
        "project_id": project["id"], "corpus_id": first["id"],
        "construct_id": flow["construct"]["id"], "text_column": "text",
        "model_name": "fake-deterministic",
    }).json()
    job = wait_for_job(client, job["id"])
    assert job["status"] == "completed", job.get("error")
    # Assert on the EXPORTED rows (what was actually analyzed), not on DB
    # metadata - the broken path kept correct metadata while scoring the
    # other corpus's texts.
    export = client.get(f"/api/jobs/{job['id']}/export").text
    data_lines = [l for l in export.splitlines()[1:] if l.strip()]
    assert len(data_lines) == 3, export
    assert "alpha" in export and "beta" not in export
