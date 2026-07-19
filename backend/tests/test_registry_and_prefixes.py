"""Registry loader + E5 prefix application (spec 0003) and warnings engine units (spec 0001)."""

import numpy as np
import pytest

from app import registry
from app.ccr import run_ccr
from app.warnings_engine import (
    detect_corpus_language,
    model_language_warning,
    short_text_warning,
)


class RecordingBackend:
    """Captures exactly what the engine sends to the encoder."""

    name = "recording"

    def __init__(self):
        self.calls: list[list[str]] = []

    def encode(self, texts, progress_cb=None):
        self.calls.append(list(texts))
        rng = np.random.default_rng(42)
        emb = rng.normal(size=(len(texts), 8))
        return emb / np.linalg.norm(emb, axis=1, keepdims=True)


# ------------------------------------------------------------------ registry
def test_registry_loads_three_models_with_minilm_default():
    models = registry.list_models()
    ids = [m.id for m in models]
    assert ids[0] == "all-minilm-l6-v2"  # default sorts first
    assert registry.default_model().id == "all-minilm-l6-v2"
    assert {"e5-large-v2", "multilingual-e5-base"} <= set(ids)


def test_e5_config_requires_prefix_on_both_sides():
    cfg = registry.get_model("e5-large-v2")
    assert cfg.requires_prefix
    assert cfg.item_prefix == "query: " and cfg.text_prefix == "query: "
    assert cfg.max_seq_length == 512 and cfg.embedding_dimension == 1024


def test_multilingual_language_set_resolves_to_real_codes():
    cfg = registry.get_model("multilingual-e5-base")
    assert cfg.language_set_name == "xlm_roberta_100"
    assert "es" in cfg.supported_languages and "sw" in cfg.supported_languages
    assert cfg.supports_language("hi") and not cfg.supports_language("xx")


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        registry.get_model("gpt-9000")


# ------------------------------------------------------------------ prefixes
def test_run_ccr_applies_prefixes_to_encoder_input_only():
    backend = RecordingBackend()
    result = run_ccr(
        ["first text here", "second text here"],
        ["an item statement"],
        backend,
        item_prefix="query: ",
        text_prefix="query: ",
    )
    item_call, text_call = backend.calls
    assert item_call == ["query: an item statement"]
    assert text_call == ["query: first text here", "query: second text here"]
    # metadata records the prefixes for the reproducibility bundle
    assert result.metadata["item_prefix"] == "query: "
    assert result.metadata["text_prefix"] == "query: "


def test_run_ccr_without_prefixes_passes_raw_strings():
    backend = RecordingBackend()
    run_ccr(["a text"], ["an item"], backend)
    assert backend.calls[0] == ["an item"] and backend.calls[1] == ["a text"]


# ------------------------------------------------------------- warnings units
def test_short_text_warning_boundary():
    w = short_text_warning(["one two three", "one two three four", "x"])
    assert w["count"] == 2  # 3-token and 1-token rows flagged; 4-token row not
    assert w["affected_rows_sample"] == [0, 2]
    assert short_text_warning(["four token sentence here"] * 3) is None


def test_language_detection_uncertain_below_min_rows():
    result, warnings = detect_corpus_language(["hello there my good friend"] * 5, "en")
    assert result.detected is None
    assert warnings[0]["code"] == "LANGUAGE_UNCERTAIN"


def test_language_mismatch_detected_deterministically():
    spanish = [f"esta es una frase de prueba número {i} sobre la vida cotidiana" for i in range(30)]
    result, warnings = detect_corpus_language(spanish, "en")
    assert result.detected == "es"
    assert any(w["code"] == "LANGUAGE_MISMATCH" for w in warnings)
    # determinism: same corpus, same outcome
    result2, _ = detect_corpus_language(spanish, "en")
    assert result2.detected == result.detected and result2.confidence == result.confidence


def test_model_language_unsupported_warning():
    w = model_language_warning("xx", "multilingual-e5-base", frozenset({"en", "es"}), "demo_set")
    assert w["code"] == "MODEL_LANGUAGE_UNSUPPORTED"
    assert model_language_warning("en", "m", frozenset({"en"}), None) is None
    assert model_language_warning("zz", "m", frozenset(), None) is None  # unknown coverage: no warning


# ------------------------------------- psyembedding models (pooling fallback)
def test_psyembedding_models_registered_with_pooling_fallback():
    """The published PsyEmbedding repos lack the 1_Pooling config their
    modules.json references, so plain SentenceTransformer(id) cannot load
    them; the registry must flag them for explicit module assembly."""
    from app import registry

    psy = [m for m in registry.list_models() if m.id.startswith("psyembedding-")]
    assert len(psy) == 4
    for m in psy:
        assert m.pooling_fallback == "mean", m.id
        assert not m.requires_prefix, m.id
        assert m.embedding_dimension == 1024 and m.max_seq_length == 512, m.id
        assert m.lazy_load, m.id


def test_repro_script_uses_explicit_modules_for_pooling_fallback():
    from app.reproducibility import script_text

    meta = {
        "construct_snapshot": {"items": [{"text": "I am satisfied.", "reverse_scored": False}],
                               "name": "X", "version": 1, "item_hash": "ab" * 16},
        "model_registry_id": "psyembedding-bert-large",
        "provider_model_id": "Culture-and-Morality-Lab/psyembedding-bert-large-uncased",
        "model_revision": "PIN_ME",
        "model_pooling_fallback": "mean",
        "model_max_seq_length": 512,
        "text_column": "text",
    }
    src = script_text(meta)
    compile(src, "reproduce_analysis.py", "exec")
    assert "st_models.Pooling" in src and "pooling_mode='mean'" in src
    # plain models keep the one-line loader
    plain = script_text({**meta, "model_pooling_fallback": None,
                         "model_registry_id": "all-minilm-l6-v2",
                         "provider_model_id": "sentence-transformers/all-MiniLM-L6-v2"})
    compile(plain, "reproduce_analysis.py", "exec")
    assert "st_models" not in plain
