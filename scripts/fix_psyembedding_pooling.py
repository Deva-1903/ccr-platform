#!/usr/bin/env python3
"""Fix the PsyEmbedding repos' broken sentence-transformers packaging.

All four Culture-and-Morality-Lab/psyembedding-* repos ship a modules.json
that references a 1_Pooling module, but the 1_Pooling/config.json it points
at was never uploaded - so SentenceTransformer(repo_id) cannot auto-load
them (the reason for the pooling_fallback workaround in models.yaml and
backend/app/ccr.py). This uploads the missing config, which makes the repos
load the standard way for everyone, platform or not.

The pooling config is derived, not assumed: pooling mode comes from the
registry entry (mean, per the model cards - the same thing the platform's
fallback has been computing all along) and the embedding dimension is read
from each repo's own config.json at the pinned revision. Adding the file
changes NOTHING numerically: same weights, same pooling math, byte-identical
embeddings - it only lets the packaged loader do what our fallback did.

Usage (write needs lab credentials: `hf auth login` or HF_TOKEN env var):
    python scripts/fix_psyembedding_pooling.py            # dry run: show plan
    python scripts/fix_psyembedding_pooling.py --write    # commit to the repos
    python scripts/fix_psyembedding_pooling.py --verify REPO_ID [REVISION]
        # download one fixed repo and check auto-load == manual assembly

After --write, finish in the platform repo (do NOT blanket-run
pin_revisions.py --write; it would repin every model, not just these):
    1. models.yaml: set the four psyembedding revision lines to the new SHAs
       printed below, and delete their pooling_fallback lines.
    2. python packages/model_registry/validate_models.py
    3. cd backend && python -m pytest -q
"""

import json
import sys

from huggingface_hub import HfApi, hf_hub_download

REPOS = [
    "Culture-and-Morality-Lab/psyembedding-bert-large-uncased",
    "Culture-and-Morality-Lab/psyembedding-roberta-large",
    "Culture-and-Morality-Lab/psyembedding-gte-large",
    "Culture-and-Morality-Lab/psyembedding-e5-large-v2",
]

COMMIT_MESSAGE = (
    "Add missing 1_Pooling/config.json referenced by modules.json\n\n"
    "modules.json declares a Pooling module at 1_Pooling, but the config "
    "was never uploaded, so SentenceTransformer auto-loading fails. Mean "
    "pooling per the model card; no change to weights or outputs."
)

# The classic 5-key Pooling config: loads on every sentence-transformers
# version (newer optional flags default to the same behavior when absent).
def pooling_config(dim: int) -> dict:
    return {
        "word_embedding_dimension": dim,
        "pooling_mode_cls_token": False,
        "pooling_mode_mean_tokens": True,
        "pooling_mode_max_tokens": False,
        "pooling_mode_mean_sqrt_len_tokens": False,
    }


def plan(api: HfApi, repo: str) -> dict | None:
    """Validate assumptions against the live repo; return the upload plan."""
    files = {f.path for f in api.list_repo_tree(repo)}
    if "1_Pooling/config.json" in files:
        print(f"  already fixed - skipping")
        return None

    modules = json.load(open(hf_hub_download(repo, "modules.json")))
    pooling = [m for m in modules if m["type"].endswith("models.Pooling")]
    assert pooling and pooling[0]["path"] == "1_Pooling", (
        f"{repo}: modules.json does not reference 1_Pooling as expected: {modules}"
    )

    hf_config = json.load(open(hf_hub_download(repo, "config.json")))
    dim = hf_config["hidden_size"]
    assert dim == 1024, f"{repo}: hidden_size {dim} != 1024 in the registry"

    content = json.dumps(pooling_config(dim), indent=2) + "\n"
    print(f"  will add 1_Pooling/config.json (mean pooling, dim {dim})")
    return {"repo": repo, "content": content}


def write(api: HfApi, p: dict) -> None:
    info = api.create_commit(
        repo_id=p["repo"],
        operations=[
            __import__("huggingface_hub").CommitOperationAdd(
                path_in_repo="1_Pooling/config.json",
                path_or_fileobj=p["content"].encode(),
            )
        ],
        commit_message=COMMIT_MESSAGE,
    )
    print(f"  committed: {info.oid}")


def verify(repo: str, revision: str | None) -> None:
    """Auto-load must equal the manual Transformer+Pooling assembly."""
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sentence_transformers import models as st_models

    texts = [
        "I am deeply satisfied with my life.",
        "The bus was late again this morning.",
        "Caring for the vulnerable is the most important virtue.",
    ]
    auto = SentenceTransformer(repo, revision=revision)
    word = st_models.Transformer(repo, max_seq_length=512)
    get_dim = getattr(word, "get_embedding_dimension", None) or word.get_word_embedding_dimension
    manual = SentenceTransformer(modules=[word, st_models.Pooling(get_dim(), pooling_mode="mean")])

    a = auto.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    m = manual.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    assert a.shape == m.shape, (a.shape, m.shape)
    max_diff = float(np.abs(a - m).max())
    print(f"{repo}: shapes {a.shape}, max |auto - manual| = {max_diff:.2e}")
    assert max_diff == 0.0, "auto-load does not match the platform's fallback assembly"
    print("verified: byte-identical to the fallback the platform has been using")


def main() -> None:
    if "--verify" in sys.argv:
        i = sys.argv.index("--verify")
        repo = sys.argv[i + 1]
        rev = sys.argv[i + 2] if len(sys.argv) > i + 2 else None
        verify(repo, rev)
        return

    do_write = "--write" in sys.argv
    api = HfApi()
    plans = []
    for repo in REPOS:
        print(repo)
        p = plan(api, repo)
        if p:
            plans.append(p)

    if not plans:
        print("\nNothing to do.")
        return
    if not do_write:
        print(f"\nDry run: {len(plans)} repo(s) need the fix. "
              "Re-run with --write (requires lab HF credentials).")
        print("Config that would be uploaded:\n" + plans[0]["content"])
        return

    who = api.whoami()
    print(f"\nWriting as: {who['name']} ({who.get('email', '?')})")
    for p in plans:
        print(p["repo"])
        write(api, p)
    print("\nDone. New commit SHAs are above - now update models.yaml "
          "(revision lines + remove pooling_fallback) per the module docstring.")


if __name__ == "__main__":
    main()
