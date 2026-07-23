"""Reproduction-script generation (spec 0002, design doc §14).

The generated script is built ONLY from the run's stored metadata - never from live
state - so it reproduces what actually ran. It must be runnable outside the platform:
input CSV + Python + internet for the (pinned) model download. No platform credentials.
"""

from __future__ import annotations


def script_filename(job_id: str | None) -> str:
    """Download name for the repro script. Single source of truth: the script's
    embedded usage instructions must match the Content-Disposition filename."""
    return f"reproduce_analysis_{job_id[:8]}.py" if job_id else "reproduce_analysis.py"


def requirements_filename(job_id: str | None) -> str:
    return f"requirements-repro_{job_id[:8]}.txt" if job_id else "requirements-repro.txt"


def _items_literal(items: list[dict]) -> str:
    """Python (not JSON) literal for the ITEMS list. json.dumps is tempting but
    emits lowercase true/false - valid Python *syntax* (bare identifiers), so it
    survives compile() checks, then NameErrors the moment the script runs."""
    if not items:
        return "[]"
    lines = ["["]
    for i in items:
        rev = bool(i.get("reverse_scored", False))
        lines.append(f'    {{"text": {i["text"]!r}, "reverse_scored": {rev}}},')
    lines.append("]")
    return "\n".join(lines)


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
        f"# Install: pip install -r {requirements_filename(metadata.get('job_id'))}",
    ]
    recorded = metadata.get("environment_pins")
    lines += recorded if recorded else _pinned_requirements(metadata)
    return "\n".join(lines) + "\n"


def record_environment(metadata: dict) -> dict:
    """Store pins in metadata at run time so exports match the executing environment."""
    metadata["environment_pins"] = _pinned_requirements(metadata)
    return metadata


def _model_loader(metadata: dict) -> tuple[str, str]:
    """(import lines, loader lines) for the pinned model - shared by the
    single- and multi-construct script templates."""
    provider = metadata.get("provider_model_id", metadata.get("model", ""))
    revision = metadata.get("model_revision")
    revision_arg = f", revision={revision!r}" if revision and revision != "PIN_ME" else ""
    pooling_fallback = metadata.get("model_pooling_fallback")
    max_seq = metadata.get("model_max_seq_length")
    if pooling_fallback:
        # Repos with incomplete sentence-transformers packaging (pooling config
        # missing) must be assembled module-by-module, exactly as the platform
        # backend does - otherwise the exported script cannot load the model.
        rev_model_kwargs = f", model_kwargs={{'revision': {revision!r}}}" if revision and revision != "PIN_ME" else ""
        model_loader = (
            f"word = st_models.Transformer({provider!r}, max_seq_length={max_seq!r}{rev_model_kwargs})\n"
            f"    get_dim = getattr(word, 'get_embedding_dimension', None) or word.get_word_embedding_dimension\n"
            f"    pool = st_models.Pooling(get_dim(), pooling_mode={pooling_fallback!r})\n"
            f"    model = SentenceTransformer(modules=[word, pool])"
        )
        st_import = "from sentence_transformers import SentenceTransformer\nfrom sentence_transformers import models as st_models"
    else:
        model_loader = f"model = SentenceTransformer({provider!r}{revision_arg})"
        st_import = "from sentence_transformers import SentenceTransformer"
    return st_import, model_loader


def script_text(metadata: dict) -> str:
    """Standalone Python script reproducing the run's similarities and scores."""
    constructs_meta = metadata.get("constructs")
    if constructs_meta and len(constructs_meta) > 1:
        return _script_text_multi(metadata, constructs_meta)

    construct = metadata.get("construct_snapshot", {})
    items = construct.get("items", [])
    model_id = metadata.get("model_registry_id", metadata.get("model", ""))
    provider = metadata.get("provider_model_id", metadata.get("model", ""))
    revision = metadata.get("model_revision")
    st_import, model_loader = _model_loader(metadata)
    item_prefix = metadata.get("item_prefix", "")
    text_prefix = metadata.get("text_prefix", "")
    text_column = metadata.get("text_column", "text")
    scoring = metadata.get("scoring", {})

    items_literal = _items_literal(items)

    # Instructions must name the files exactly as they download (run-id suffix
    # and all) and use the corpus the run actually analyzed as the example arg.
    script_name = script_filename(metadata.get("job_id"))
    reqs_name = requirements_filename(metadata.get("job_id"))
    corpus_csv = metadata.get("corpus_file") or "your_corpus.csv"
    corpus_arg = f'"{corpus_csv}"' if any(c.isspace() for c in corpus_csv) else corpus_csv

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
    pip install -r {reqs_name}
    python {script_name} {corpus_arg}
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
        raise SystemExit("Usage: python {script_name} <corpus.csv>")
    main(sys.argv[1])
'''


def _constructs_literal(constructs_meta: list[dict]) -> str:
    """Python literal for the multi-construct CONSTRUCTS list (see
    _items_literal for why json.dumps is unusable here)."""
    lines = ["["]
    for c in constructs_meta:
        items = c.get("snapshot", {}).get("items", [])
        lines.append("    {")
        lines.append(f"        \"name\": {c.get('name', '')!r},")
        lines.append(f"        \"column_prefix\": {c.get('column_prefix', '')!r},")
        lines.append("        \"items\": [")
        for i in items:
            rev = bool(i.get("reverse_scored", False))
            lines.append(f'            {{"text": {i["text"]!r}, "reverse_scored": {rev}}},')
        lines.append("        ],")
        lines.append("    },")
    lines.append("]")
    return "\n".join(lines)


def _script_text_multi(metadata: dict, constructs_meta: list[dict]) -> str:
    """Multi-construct variant: the corpus is embedded ONCE, then every
    construct is scored against the same document embeddings - the exact
    computation the platform ran, prefixed columns and all."""
    model_id = metadata.get("model_registry_id", metadata.get("model", ""))
    provider = metadata.get("provider_model_id", metadata.get("model", ""))
    revision = metadata.get("model_revision")
    st_import, model_loader = _model_loader(metadata)
    item_prefix = metadata.get("item_prefix", "")
    text_prefix = metadata.get("text_prefix", "")
    text_column = metadata.get("text_column", "text")
    scoring = metadata.get("scoring", {})

    construct_lines = "\n".join(
        f"#   {c.get('name', '?')} (hash {c.get('items_sha256_16', '?')}, "
        f"columns {c.get('column_prefix', '?')}_*)"
        for c in constructs_meta
    )

    script_name = script_filename(metadata.get("job_id"))
    reqs_name = requirements_filename(metadata.get("job_id"))
    corpus_csv = metadata.get("corpus_file") or "your_corpus.csv"
    corpus_arg = f'"{corpus_csv}"' if any(c.isspace() for c in corpus_csv) else corpus_csv

    return f'''#!/usr/bin/env python3
"""Reproduce CCR analysis independently of the platform (multi-construct run).

run_id:                {metadata.get("job_id", "?")}
created_at:            {metadata.get("started_at", "?")}
platform_version:      {metadata.get("platform_version", "?")}
output_schema_version: {metadata.get("output_schema_version", "1.1")}
model:                 {model_id} -> {provider} (revision: {revision or "unpinned"})
scoring:               adjustment_strategy={scoring.get("adjustment_strategy", "none")}, aggregate={scoring.get("aggregate", "mean_all_items")}
"""
# Constructs scored in this run:
{construct_lines}
#
# Usage:
#     pip install -r {reqs_name}
#     python {script_name} {corpus_arg}
# Outputs reproduced_results.csv with the same prefixed similarity columns as
# the platform export ({{prefix}}_sim_item_N, {{prefix}}_ccr_score).

import sys

import numpy as np
import pandas as pd
{st_import}

TEXT_COLUMN = {text_column!r}
ITEM_PREFIX = {item_prefix!r}   # model-required prefix (E5 family); empty = none
TEXT_PREFIX = {text_prefix!r}

CONSTRUCTS = {_constructs_literal(constructs_meta)}


def main(csv_path: str) -> None:
    df = pd.read_csv(csv_path)
    texts_all = df[TEXT_COLUMN].astype("string")
    mask = texts_all.notna() & (texts_all.str.strip() != "")
    work = df.loc[mask].reset_index(drop=True)          # platform drops empty rows the same way
    texts = work[TEXT_COLUMN].astype(str).tolist()

    {model_loader}
    doc_texts = [TEXT_PREFIX + t for t in texts]
    doc_emb = model.encode(doc_texts, convert_to_numpy=True, normalize_embeddings=True)

    for construct in CONSTRUCTS:                         # corpus embedded once, scored per construct
        item_texts = [ITEM_PREFIX + i["text"] for i in construct["items"]]
        item_emb = model.encode(item_texts, convert_to_numpy=True, normalize_embeddings=True)
        sims = doc_emb @ item_emb.T                      # normalized -> cosine similarity
        prefix = construct["column_prefix"]
        for j in range(sims.shape[1]):
            work[f"{{prefix}}_sim_item_{{j + 1}}"] = np.round(sims[:, j], 6)
        work[f"{{prefix}}_ccr_score"] = np.round(sims.mean(axis=1), 6)

    score_cols = [c["column_prefix"] + "_ccr_score" for c in CONSTRUCTS]
    print("Construct score correlations (Pearson):")
    print(work[score_cols].corr().round(4).to_string())

    work.to_csv("reproduced_results.csv", index=False)
    print(f"Wrote reproduced_results.csv ({{len(work)}} rows, {{len(CONSTRUCTS)}} constructs).")
    print("Compare against the platform export - values should match to ~1e-5.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python {script_name} <corpus.csv>")
    main(sys.argv[1])
'''
