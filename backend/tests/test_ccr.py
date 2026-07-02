"""Unit tests for the CCR engine (deterministic fake backend — no torch)."""

import numpy as np
import pytest

from app.ccr import HashEmbeddingBackend, get_backend, run_ccr, FAKE_MODEL_NAME


@pytest.fixture()
def backend():
    return HashEmbeddingBackend()


def test_fake_backend_is_deterministic(backend):
    a = backend.encode(["I am satisfied with my life."])
    b = backend.encode(["I am satisfied with my life."])
    np.testing.assert_array_equal(a, b)


def test_embeddings_are_normalized(backend):
    emb = backend.encode(["hello world", "another sentence here"])
    norms = np.linalg.norm(emb, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-9)


def test_run_ccr_shapes(backend):
    texts = ["one text", "two texts here", "three texts here now"]
    items = ["item alpha", "item beta"]
    result = run_ccr(texts, items, backend)
    assert result.similarities.shape == (3, 2)
    assert result.scores.shape == (3,)
    np.testing.assert_allclose(result.scores, result.similarities.mean(axis=1))


def test_shared_vocabulary_scores_higher(backend):
    items = ["I am satisfied with my life."]
    texts = [
        "I am so satisfied with my life these days.",  # heavy vocab overlap
        "The train timetable changed on Tuesday.",  # no overlap
    ]
    result = run_ccr(texts, items, backend)
    assert result.scores[0] > result.scores[1]


def test_metadata_records_reproducibility_fields(backend):
    result = run_ccr(["some text"], ["an item"], backend)
    meta = result.metadata
    for key in ("model", "n_texts", "n_items", "items_sha256_16", "started_at", "numpy"):
        assert key in meta
    assert meta["model"] == FAKE_MODEL_NAME


def test_empty_inputs_raise(backend):
    with pytest.raises(ValueError):
        run_ccr([], ["item"], backend)
    with pytest.raises(ValueError):
        run_ccr(["text"], [], backend)


def test_get_backend_env_override(monkeypatch):
    monkeypatch.setenv("CCR_FAKE_EMBEDDINGS", "1")
    assert isinstance(get_backend("sentence-transformers/all-MiniLM-L6-v2"), HashEmbeddingBackend)
