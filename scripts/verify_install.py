#!/usr/bin/env python3
"""One-shot install verification: runs a real CCR computation end-to-end.

Usage (from repo root, inside the backend venv):
    python scripts/verify_install.py

Downloads the default model on first run (~90 MB), embeds a 4-text toy
corpus against the SWLS items, and prints the scores. If the satisfaction
texts outrank the neutral ones, the full stack works.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ccr import SentenceTransformerBackend, run_ccr  # noqa: E402
from app.seed_constructs import SEED_CONSTRUCTS  # noqa: E402

TEXTS = [
    "I am deeply satisfied with my life and grateful for how things turned out.",
    "In most ways, my life is everything I hoped it would be.",
    "The bus was late again this morning.",
    "We repainted the kitchen over the weekend.",
]

def main() -> int:
    swls = next(c for c in SEED_CONSTRUCTS if c["name"] == "Satisfaction with Life")
    print("Loading model (first run downloads ~90 MB)…")
    backend = SentenceTransformerBackend("sentence-transformers/all-MiniLM-L6-v2")
    result = run_ccr(TEXTS, swls["items"], backend)

    print(f"\nModel: {result.metadata['model']} (dim {result.metadata['embedding_dim']})")
    for text, score in zip(TEXTS, result.scores):
        print(f"  {score:6.3f}  {text}")

    ok = min(result.scores[0], result.scores[1]) > max(result.scores[2], result.scores[3])
    print("\nPASS — satisfaction texts outrank neutral texts." if ok else "\nCHECK — unexpected ordering; inspect installation.")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
