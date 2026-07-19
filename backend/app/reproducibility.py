"""Reproduction-script generation (spec 0002, design doc §14).

The generated script is built ONLY from the run's stored metadata - never from live
state - so it reproduces what actually ran. It must be runnable outside the platform:
input CSV + Python + internet for the (pinned) model download. No platform credentials.
"""

from __future__ import annotations

import json


def _pinned_requirements(metadata: dict) -> list[str]:
    """Exact versions of the packages the analysis math depends on."""
    from importlib.metadata import PackageNotFoundError, version

    pins = []
    for pkg in ("sentence-transformers", "torch", "numpy", "pandas"):
        try:
            pins.append(f"{pkg}=={version(pkg)}")
        except PackageNotFoundError:
            continue
    return pins


def requirements_text(metadata: dict) -> str:
    lines = [
        "# Reproduction environment for CCR run " + metadata.get("job_id", "?"),
        "# Install: pip install -r requirements-repro.txt",
    ]
    recorded = metadata.get("environment_pins")
    lines += recorded if recorded else _pinned_requirements(metadata)
    return "\n".join(lines) + "\n"


def record_environment(metadata: dict) -> dict:
    """Store pins in metadata at run time so exports match the executing environment."""
    metadata["environment_pins"] = _pinned_requirements(metadata)
    return metadata


def script_text(metadata: dict) -> str:
    """Standalone Python script reproducing the run's similarities and scores."""
    construct = metadata.get("construct_snapshot", {})
    items = construct.get("items", [])
    model_id = metadata.get("model_registry_id", metadata.get("model", ""))
    provider = metadata.get("provider_model_id", metadata.get("model", ""))
    revision = metadata.get("model_revision")
    revision_arg = f", revision={revision!r}" if revision and revision != "PIN_ME" else ""
    pooling_fallback = metadata.get("model_pooling_fallback")
    max_seq = metadata.get("model_max_seq_length")
    if pooling_fallback:
        # Repos with incomplete sentence-transformers packaging (pooling config
        # missing) must be assembled module-by-module, exactly as the platform
        # backend does - otherwise the exported script cannot load the model.
        rev_model_args = f", model_args={{'revision': {revision!r}}}" if revision and revision != "PIN_ME" else ""
        model_loader = (
            f"word = st_models.Transformer({provider!r}, max_seq_length={max_seq!r}{rev_model_args})\n"
            f"    get_dim = getattr(word, 'get_embedding_dimension', None) or word.get_word_embedding_dimension\n"
            f"    pool = st_models.Pooling(get_dim(), pooling_mode={pooling_fallback!r})\n"
            f"    model = SentenceTransformer(modules=[word, pool])"
        )
        st_import = "from sentence_transformers import SentenceTransformer\nfrom sentence_transformers import models as st_models"
    else:
        model_loader = f"model = SentenceTransformer({provider!r}{revision_arg})"
        st_import = "from sentence_transformers import SentenceTransformer"
    item_prefix = metadata.get("item_prefix", "")
    text_prefix = metadata.get("text_prefix", "")
    text_column = metadata.get("text_column", "text")
    scoring = metadata.get("scoring", {})

    items_literal = json.dumps(
        [{"text": i["text"], "reverse_scored": i.get("reverse_scored", False)} for i in items],
        indent=4, ensure_ascii=False,
    )

    return f'''#!/usr/bin/env python3
"""Reproduce CCR analysis independently of the platform.

run_id:                {metadata.get("job_id", "?")}
created_at:            {metadata.get("started_at", "?")}
platform_version:      {metadata.get("platform_version", "?")}
output_schema_version: {metadata.get("output_schema_version", "1.0")}
construct:             {construct.get("name", "?")} (v{construct.get("version", "?")}, hash {construct.get("item_hash", "?")[:16]})
model:                 {model_id} -> {provider} (revision: {revision or "unpinned"})
scoring:               adjustment_strategy={scoring.get("adjustment_strategy", "none")}, aggregate={scoring.get("aggregate", "mean_all_items")}

Usage:
    pip install -r requirements-repro.txt
    python reproduce_analysis.py your_corpus.csv
Outputs reproduced_results.csv with the same similarity columns as the platform export.
"""

import sys

import numpy as np
import pandas as pd
{st_import}

TEXT_COLUMN = {text_column!r}
ITEM_PREFIX = {item_prefix!r}   # model-required prefix (E5 family); empty = none
TEXT_PREFIX = {text_prefix!r}

ITEMS = {items_literal}


def main(csv_path: str) -> None:
    df = pd.read_csv(csv_path)
    texts_all = df[TEXT_COLUMN].astype("string")
    mask = texts_all.notna() & (texts_all.str.strip() != "")
    work = df.loc[mask].reset_index(drop=True)          # platform drops empty rows the same way
    texts = work[TEXT_COLUMN].astype(str).tolist()

    {model_loader}
    item_texts = [ITEM_PREFIX + i["text"] for i in ITEMS]
    doc_texts = [TEXT_PREFIX + t for t in texts]

    item_emb = model.encode(item_texts, convert_to_numpy=True, normalize_embeddings=True)
    doc_emb = model.encode(doc_texts, convert_to_numpy=True, normalize_embeddings=True)

    sims = doc_emb @ item_emb.T                          # normalized -> cosine similarity
    for j in range(sims.shape[1]):
        work[f"sim_item_{{j + 1}}"] = np.round(sims[:, j], 6)
    work["ccr_score"] = np.round(sims.mean(axis=1), 6)

    work.to_csv("reproduced_results.csv", index=False)
    print(f"Wrote reproduced_results.csv ({{len(work)}} rows, {{sims.shape[1]}} items).")
    print("Compare against the platform export - values should match to ~1e-5.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python reproduce_analysis.py <corpus.csv>")
    main(sys.argv[1])
'''
