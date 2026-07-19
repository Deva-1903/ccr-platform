"""CCR engine - Contextualized Construct Representations.

Method (Atari, Omrani et al.): embed validated questionnaire items and the
texts to be analyzed with a contextual sentence-embedding model, then take
the cosine similarity between each text and each item. The per-item
similarities are the text's "loadings" on the construct; their mean is the
overall CCR score.

The embedding model is injected behind a small interface so that:
  * production uses sentence-transformers (local, pinned, reproducible -
    corpora never leave the machine), and
  * tests/CI use a deterministic hash-based embedder with no ML dependency.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

import numpy as np

ProgressCb = Callable[[float], None]

FAKE_MODEL_NAME = "fake-deterministic"


class EmbeddingBackend(Protocol):
    name: str

    def encode(self, texts: list[str], progress_cb: ProgressCb | None = None) -> np.ndarray:
        """Return L2-normalized embeddings, shape (len(texts), dim)."""
        ...


class SentenceTransformerBackend:
    """Local sentence-transformers backend (lazy import, model cached per process)."""

    _cache: dict[str, object] = {}

    def __init__(
        self,
        model_name: str,
        revision: str | None = None,
        pooling_fallback: str | None = None,
        max_seq_length: int | None = None,
    ):
        self.name = model_name
        self.revision = revision
        self.pooling_fallback = pooling_fallback
        self._max_seq_length = max_seq_length

    def _model(self):
        if self.name not in self._cache:
            from sentence_transformers import SentenceTransformer  # lazy: heavy import

            if self.pooling_fallback:
                # Registry-flagged repos ship modules.json without the pooling
                # config it references, so auto-loading fails; build the module
                # stack explicitly with the pooling the model card documents.
                from sentence_transformers import models as st_models

                margs = {"model_args": {"revision": self.revision}} if self.revision else {}
                word = st_models.Transformer(
                    self.name, max_seq_length=self._max_seq_length, **margs
                )
                # renamed in newer sentence-transformers; support both
                get_dim = getattr(word, "get_embedding_dimension", None) or word.get_word_embedding_dimension
                pool = st_models.Pooling(get_dim(), pooling_mode=self.pooling_fallback)
                self._cache[self.name] = SentenceTransformer(modules=[word, pool])
            else:
                kwargs = {"revision": self.revision} if self.revision else {}
                self._cache[self.name] = SentenceTransformer(self.name, **kwargs)
        return self._cache[self.name]

    @property
    def max_seq_length(self) -> int | None:
        try:
            return int(self._model().max_seq_length)
        except Exception:
            return None

    def encode(self, texts: list[str], progress_cb: ProgressCb | None = None) -> np.ndarray:
        model = self._model()
        batch, out = 64, []
        for i in range(0, len(texts), batch):
            emb = model.encode(
                texts[i : i + batch],
                convert_to_numpy=True,
                normalize_embeddings=True, # scales every vector to length 1
                show_progress_bar=False,
            )
            out.append(emb)
            if progress_cb:
                progress_cb(min(1.0, (i + batch) / max(1, len(texts))))
        return np.vstack(out)


class HashEmbeddingBackend:
    """Deterministic bag-of-words hash embeddings for tests and CI.

    Texts sharing vocabulary get higher cosine similarity, so end-to-end
    behavior (ranking, export shape, reproducibility metadata) is testable
    without torch. Never used for research output.
    """

    dim = 384
    max_seq_length = None

    def __init__(self):
        self.name = FAKE_MODEL_NAME

    def _embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float64)
        for token in re.findall(r"[a-z']+", text.lower()):
            h = hashlib.sha256(token.encode()).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def encode(self, texts: list[str], progress_cb: ProgressCb | None = None) -> np.ndarray:
        out = np.vstack([self._embed_one(t) for t in texts])
        if progress_cb:
            progress_cb(1.0)
        return out


def get_backend(model_id: str) -> EmbeddingBackend:
    """Resolve a REGISTRY model id (or the test fake) to an embedding backend."""
    if model_id == FAKE_MODEL_NAME or os.environ.get("CCR_FAKE_EMBEDDINGS") == "1":
        return HashEmbeddingBackend()
    from . import registry  # local import: engine stays importable without yaml deps

    cfg = registry.get_model(model_id)
    return SentenceTransformerBackend(
        cfg.provider_model_id,
        revision=cfg.pinned_revision,
        pooling_fallback=cfg.pooling_fallback,
        max_seq_length=cfg.max_seq_length,
    )


@dataclass
class CCRResult:
    similarities: np.ndarray  # (n_docs, n_items)
    scores: np.ndarray  # (n_docs,) mean over items
    metadata: dict
    doc_embeddings: np.ndarray | None = None  # exposed so jobs.py can cache them


def encode_unique(backend: EmbeddingBackend, texts: list[str],
                  progress_cb: ProgressCb | None = None) -> np.ndarray:
    """Encode only unique texts, then scatter back to full row order.

    Duplicate rows are common in social-media corpora; embeddings are
    deterministic per text, so encoding each unique text once is a pure
    speedup with bit-identical output.
    """
    unique: dict[str, int] = {}
    for t in texts:
        if t not in unique:
            unique[t] = len(unique)
    if len(unique) == len(texts):
        return backend.encode(texts, progress_cb=progress_cb)
    unique_texts = list(unique.keys())
    unique_emb = backend.encode(unique_texts, progress_cb=progress_cb)
    idx = np.fromiter((unique[t] for t in texts), dtype=np.int64, count=len(texts))
    return unique_emb[idx]


# Item-set embeddings are tiny and constantly reused (same construct run
# against many corpora) - cache them per (model, exact item wording).
_item_embedding_cache: dict[tuple[str, str], np.ndarray] = {}


def encode_items_cached(backend: EmbeddingBackend, items: list[str]) -> tuple[np.ndarray, bool]:
    key = (backend.name, "\n".join(items))
    if key in _item_embedding_cache:
        return _item_embedding_cache[key], True
    emb = backend.encode(items)
    if backend.name != FAKE_MODEL_NAME:  # keep tests hermetic
        _item_embedding_cache[key] = emb
    return emb, False


def run_ccr(
    texts: list[str],
    items: list[str],
    backend: EmbeddingBackend,
    progress_cb: ProgressCb | None = None,
    item_prefix: str = "",
    text_prefix: str = "",
    doc_embeddings: np.ndarray | None = None,
) -> CCRResult:
    """Compute CCR loadings: cosine(text, item) for every text × item pair.

    Prefixes come from the model registry's usage_config - E5-family models require
    "query: " on BOTH sides for symmetric similarity. Prefixed strings feed the
    encoder only; raw wording is what gets hashed and exported.
    """
    if not texts:
        raise ValueError("Corpus contains no non-empty texts.")
    if not items:
        raise ValueError("Construct has no items.")

    started = datetime.now(timezone.utc)

    items_for_encoding = [item_prefix + i for i in items] if item_prefix else items
    item_emb, items_cached = encode_items_cached(backend, items_for_encoding)
    if progress_cb:
        progress_cb(0.02)

    def doc_progress(frac: float):
        if progress_cb:
            progress_cb(0.02 + 0.93 * frac)

    embeddings_from_cache = doc_embeddings is not None and len(doc_embeddings) == len(texts)
    if embeddings_from_cache:
        doc_emb = doc_embeddings  # precomputed for this exact corpus+model+prefix (jobs.py cache)
        doc_progress(1.0)
    else:
        texts_for_encoding = [text_prefix + t for t in texts] if text_prefix else texts
        doc_emb = encode_unique(backend, texts_for_encoding, progress_cb=doc_progress)

    # Both matrices are L2-normalized -> cosine similarity is a dot product.
    sims = doc_emb @ item_emb.T   # similarity of every text to every item
    scores = sims.mean(axis=1)   # average across items = the CCR score

    finished = datetime.now(timezone.utc)
    items_hash = hashlib.sha256("\n".join(items).encode()).hexdigest()[:16]

    metadata = {
        "method": "CCR (Contextualized Construct Representations)",
        "model": backend.name,
        "embedding_dim": int(doc_emb.shape[1]),
        "model_max_seq_length": getattr(backend, "max_seq_length", None),
        "item_embeddings_from_cache": items_cached,
        "doc_embeddings_from_cache": embeddings_from_cache,
        "n_texts": len(texts),
        "n_items": len(items),
        "items_sha256_16": items_hash,
        "item_prefix": item_prefix,
        "text_prefix": text_prefix,
        "similarity": "cosine",
        "score": "mean of per-item cosine similarities",
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "duration_seconds": round((finished - started).total_seconds(), 2),
    }
    try:
        import sentence_transformers

        metadata["sentence_transformers"] = sentence_transformers.__version__
    except ImportError:
        pass

    if progress_cb:
        progress_cb(0.97)
    return CCRResult(similarities=sims, scores=scores, metadata=metadata, doc_embeddings=doc_emb)
