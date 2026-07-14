"""Storage interface: local backend (default) and S3/R2 backend via a fake
client - proves production object storage works end to end (upload -> run ->
export -> retention delete) without any network or boto3 dependency."""

import io
import time

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app


class FakeS3:
    """Minimal S3 client: just what storage.py calls."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.read()

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"ContentLength": len(self.objects[Key])}

    def download_file(self, Bucket, Key, Filename):
        with open(Filename, "wb") as f:
            f.write(self.objects[Key])

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


@pytest.fixture()
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setenv("CCR_STORAGE", "s3")
    monkeypatch.setenv("CCR_S3_BUCKET", "ccr-test")
    monkeypatch.setattr(storage, "_client", fake)
    yield fake
    monkeypatch.setattr(storage, "_client", None)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def csv_rows(n: int) -> bytes:
    return ("text\n" + "\n".join(f"sample sentence number {i} here" for i in range(n))).encode()


def wait_for_job(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.05)
    raise TimeoutError(job_id)


# ------------------------------------------------------------------ unit
def test_s3_roundtrip(s3, tmp_path):
    locator = storage.store_bytes("corpora", "abc.csv", b"text\nhello world row\n")
    assert locator == "s3://corpora/abc.csv"
    assert storage.exists(locator)

    local, is_temp = storage.fetch_to_local(locator)
    assert is_temp and local.read_bytes().startswith(b"text")
    local.unlink()

    assert b"".join(storage.open_stream(locator)) == b"text\nhello world row\n"
    storage.delete(locator)
    assert not storage.exists(locator)
    assert s3.objects == {}


def test_local_backend_unchanged(tmp_path):
    locator = storage.store_bytes("corpora", "local_check.csv", b"data")
    assert not storage.is_s3(locator)
    local, is_temp = storage.fetch_to_local(locator)
    assert not is_temp and local.read_bytes() == b"data"
    storage.delete(locator)
    assert not storage.exists(locator)


# ------------------------------------------------------------ end to end
def test_full_flow_on_s3_backend(client, s3):
    """Signed-in upload -> corpus lands in the bucket -> run materializes a
    temp copy -> result CSV lands in the bucket -> export streams it ->
    project delete empties the bucket."""
    client.post(
        "/api/auth/register",
        json={"email": "s3user@test.edu", "password": "password123", "name": "S3"},
    )
    project = client.post("/api/projects", json={"name": "S3Flow"}).json()
    corpus = client.post(
        f"/api/projects/{project['id']}/corpora",
        files={"file": ("c.csv", io.BytesIO(csv_rows(6)), "text/csv")},
    ).json()
    assert any(k.startswith("corpora/") for k in s3.objects)

    construct = client.get("/api/constructs").json()[0]
    job = client.post(
        "/api/jobs",
        json={
            "project_id": project["id"],
            "corpus_id": corpus["id"],
            "construct_id": construct["id"],
            "text_column": "text",
            "model_name": "fake-deterministic",
        },
    ).json()
    job = wait_for_job(client, job["id"])
    assert job["status"] == "completed"
    assert any(k.startswith("results/") for k in s3.objects)

    export = client.get(f"/api/jobs/{job['id']}/export")
    assert export.status_code == 200
    assert b"ccr_score" in export.content

    client.delete(f"/api/projects/{project['id']}")
    assert s3.objects == {}  # cascade emptied the bucket


def test_anonymous_run_deletes_s3_corpus(client, s3):
    project = client.post("/api/projects", json={"name": "S3Anon"}).json()
    corpus = client.post(
        f"/api/projects/{project['id']}/corpora",
        files={"file": ("c.csv", io.BytesIO(csv_rows(5)), "text/csv")},
    ).json()
    construct = client.get("/api/constructs").json()[0]
    job = client.post(
        "/api/jobs",
        json={
            "project_id": project["id"],
            "corpus_id": corpus["id"],
            "construct_id": construct["id"],
            "text_column": "text",
            "model_name": "fake-deterministic",
        },
    ).json()
    job = wait_for_job(client, job["id"])
    assert job["status"] == "completed"
    assert not any(k.startswith("corpora/") for k in s3.objects)  # upload gone
    assert any(k.startswith("results/") for k in s3.objects)  # results kept for TTL
