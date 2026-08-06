"""LLM item generation (ITEM_GENERATION.md): endpoint gating, daily cap,
and provenance. The Anthropic call itself is always mocked - these tests
exercise our plumbing, not the model."""

import pytest
from fastapi.testclient import TestClient

from app import item_generation
from app.construct_lib import construct_snapshot
from app.db import SessionLocal
from app.main import app
from app.models import Construct

FAKE_DRAFT = item_generation.GeneratedItems(
    items=[
        "I often pause to appreciate the good things in my life.",
        "I feel thankful for the people who support me.",
        "I notice small moments that make my day better.",
    ],
    notes="All items positively keyed.",
)

GEN_BODY = {
    "name": "Gratitude",
    "description": "Noticing and appreciating the positive things in one's life.",
    "n_items": 10,
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # lifespan seeds the construct library
        yield c


def register(client, email, name="Gen Tester"):
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "pw123456789", "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp


def fake_generate(**_kwargs):
    return FAKE_DRAFT


# ---------------------------------------------------------------- providers
def test_provider_inference(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("CCR_GENERATION_PROVIDER", raising=False)
    monkeypatch.delenv("CCR_GENERATION_MODEL", raising=False)
    assert item_generation.provider() is None
    assert item_generation.configured() is False

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    assert item_generation.provider() == "groq"
    assert item_generation.generation_model() == item_generation.GROQ_MODEL_DEFAULT

    # Anthropic wins once its key lands (the decided target)...
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert item_generation.provider() == "anthropic"
    assert item_generation.generation_model() == item_generation.ANTHROPIC_MODEL_DEFAULT

    # ...unless the provider is forced explicitly.
    monkeypatch.setenv("CCR_GENERATION_PROVIDER", "groq")
    assert item_generation.provider() == "groq"


def test_groq_response_parsing(monkeypatch):
    """The Groq path end-to-end with the HTTP call stubbed."""
    import io
    import json as jsonlib

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.delenv("CCR_GENERATION_PROVIDER", raising=False)

    groq_reply = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"items": ["I feel thankful for the people around me.", '
                        '"", "I feel thankful for the people around me."], '
                        '"notes": null}'
                    )
                }
            }
        ]
    }

    def fake_urlopen(req, timeout=None):
        assert "api.groq.com" in req.full_url
        return io.BytesIO(jsonlib.dumps(groq_reply).encode())  # BytesIO is a context manager

    monkeypatch.setattr(item_generation.urllib.request, "urlopen", fake_urlopen)
    draft = item_generation.generate_items(name="Gratitude", description="Being thankful.")
    # empties and duplicates cleaned; one item survives
    assert draft.items == ["I feel thankful for the people around me."]


# ------------------------------------------------------------------ gating
def test_anonymous_is_refused(client):
    client.cookies.clear()
    resp = client.post("/api/constructs/generate-items", json=GEN_BODY)
    assert resp.status_code == 401
    assert "Sign in" in resp.json()["detail"]


def test_unconfigured_instance_returns_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    register(client, "gen503@test.edu")
    resp = client.post("/api/constructs/generate-items", json=GEN_BODY)
    assert resp.status_code == 503
    client.cookies.clear()


def test_anon_auth_me_reports_configured_state(client, monkeypatch):
    client.cookies.clear()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/api/auth/me").json()["generation_available"] is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # anon sees the feature exists (for the sign-in nudge); the endpoint
    # itself still refuses anonymous calls (test_anonymous_is_refused)
    assert client.get("/api/auth/me").json()["generation_available"] is True


# ------------------------------------------------------------------ success
def test_generation_preview_and_usage(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(item_generation, "generate_items", fake_generate)
    register(client, "genok@test.edu")

    resp = client.post("/api/constructs/generate-items", json=GEN_BODY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == FAKE_DRAFT.items
    assert body["notes"] == FAKE_DRAFT.notes
    assert body["generation"]["prompt_version"] == item_generation.PROMPT_VERSION
    assert body["generation"]["model"]
    assert body["generations_used_today"] == 1
    assert body["max_generations_per_day"] == item_generation.user_max_generations_per_day()

    # Nothing was saved - a preview only.
    names = [c["name"] for c in client.get("/api/constructs").json()]
    assert "Gratitude" not in names

    # auth/me mirrors the usage so the UI can show "X of N used today".
    me = client.get("/api/auth/me").json()
    assert me["generation_available"] is True
    assert me["usage"]["generations_used_today"] == 1
    client.cookies.clear()


def test_daily_cap_enforced(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CCR_USER_MAX_GENERATIONS_PER_DAY", "2")
    monkeypatch.setattr(item_generation, "generate_items", fake_generate)
    register(client, "gencap@test.edu")

    for _ in range(2):
        assert client.post("/api/constructs/generate-items", json=GEN_BODY).status_code == 200
    resp = client.post("/api/constructs/generate-items", json=GEN_BODY)
    assert resp.status_code == 429
    assert "Daily limit" in resp.json()["detail"]
    client.cookies.clear()


def test_generation_error_maps_to_http(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def boom(**_kwargs):
        raise item_generation.GenerationError("Service hiccup.", status_code=502)

    monkeypatch.setattr(item_generation, "generate_items", boom)
    register(client, "generr@test.edu")
    resp = client.post("/api/constructs/generate-items", json=GEN_BODY)
    assert resp.status_code == 502
    assert resp.json()["detail"] == "Service hiccup."
    # Failed attempts do not burn quota.
    me = client.get("/api/auth/me").json()
    assert me["usage"]["generations_used_today"] == 0
    client.cookies.clear()


# --------------------------------------------------------------- provenance
def test_saved_generated_construct_carries_provenance(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(item_generation, "generate_items", fake_generate)
    register(client, "genprov@test.edu")

    draft = client.post("/api/constructs/generate-items", json=GEN_BODY).json()
    created = client.post(
        "/api/constructs",
        json={
            "name": "Gratitude (generated)",
            "description": GEN_BODY["description"],
            "items": draft["items"],
            "generation": draft["generation"],
        },
    ).json()
    assert created["ai_generated"] is True
    assert created["verification_status"] == "draft"

    # The label survives the round trip through the list endpoint...
    listed = next(
        c for c in client.get("/api/constructs").json() if c["id"] == created["id"]
    )
    assert listed["ai_generated"] is True

    # ...and flows into the run-metadata snapshot with the cautionary note.
    db = SessionLocal()
    try:
        snapshot = construct_snapshot(db.get(Construct, created["id"]))
    finally:
        db.close()
    assert snapshot["source_type"] == "llm_generated"
    assert snapshot["generation"]["prompt_version"] == item_generation.PROMPT_VERSION
    assert "AI-generated" in snapshot["items_source_note"]
    client.cookies.clear()


def test_manual_construct_is_not_labeled(client):
    created = client.post(
        "/api/constructs",
        json={"name": "Hand-written", "items": ["I write my own items."]},
    ).json()
    assert created["ai_generated"] is False
    db = SessionLocal()
    try:
        snapshot = construct_snapshot(db.get(Construct, created["id"]))
    finally:
        db.close()
    assert snapshot["source_type"] == "user_custom"
    assert "generation" not in snapshot
