#!/usr/bin/env python3
"""Measure embedding throughput per model - resolves the registry's
`expected_time_per_1k_texts_cpu: benchmark_required` fields with real numbers.

Run this ON the target host: throughput is dominated by per-core CPU speed, so
a laptop figure can overstate a shared cloud vCPU by 2-4x. On a Space, open a
terminal in the container (or add a one-off startup command) and run:

    python scripts/bench_models.py --threads 2

Pinning --threads to the host's vCPU count matters: torch otherwise grabs every
core it can see and reports a number the app will never reproduce, since jobs
run one at a time on a single worker thread (see app/jobs.py).

The row shapes below bracket the realistic CCR corpus range - short social
posts, survey open-ends, and long documents that fill the model's token window.
Multiply s/1k by (rows / 1000) to get expected job wall-clock, then sanity-check
it against how long a job may run before a host restart can kill it.
"""

from __future__ import annotations

import argparse
import os
import time

# Thread caps must be set before torch/transformers import to take effect.
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--threads", type=int, default=2, help="CPU threads (match host vCPUs)")
parser.add_argument("--batch", type=int, default=64, help="must match ccr.py's encode batch")
parser.add_argument("--models", default="", help="comma-separated registry ids (default: all)")
parser.add_argument("--quick", action="store_true", help="fewer texts per shape")
args = parser.parse_args()

for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[var] = str(args.threads)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import torch  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

torch.set_num_threads(args.threads)

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app import registry  # noqa: E402

_WORDS = (
    "participants reported that the collaborative environment meaningfully shaped "
    "their sense of belonging within the wider research group over the study period"
).split()


def synth(n_words: int) -> str:
    return " ".join((_WORDS * 40)[:n_words])


SHAPES = [
    ("short  (~15w, social post)", 15),
    ("medium (~60w, survey open-end)", 60),
    ("long   (~250w, document)", 250),
]


def bench(model: SentenceTransformer, n_words: int, n: int) -> float:
    """Return seconds per 1,000 texts."""
    texts = [synth(n_words)] * n
    model.encode(texts[: args.batch], batch_size=args.batch, show_progress_bar=False)  # warm
    start = time.perf_counter()
    model.encode(
        texts, batch_size=args.batch, show_progress_bar=False, normalize_embeddings=True
    )
    return (time.perf_counter() - start) / n * 1000


def main() -> None:
    wanted = [m.strip() for m in args.models.split(",") if m.strip()]
    models = [m for m in registry.list_models() if not wanted or m.id in wanted]
    if not models:
        raise SystemExit(f"no registry models matched {wanted!r}")

    print(f"threads={args.threads}  batch={args.batch}  torch={torch.__version__}")
    print("(load times exclude first-run model download)\n")

    for cfg in models:
        try:
            t0 = time.perf_counter()
            model = SentenceTransformer(cfg.provider_model_id)
            model.eval()
            load = time.perf_counter() - t0
        except Exception as exc:  # a heavy model may not fit; keep going
            print(f"{cfg.id}: SKIPPED ({type(exc).__name__}: {exc})\n")
            continue

        print(f"{cfg.id}  (max_seq={model.max_seq_length}, load {load:.1f}s)")
        for label, n_words in SHAPES:
            # Fast models need enough batches that warm-up noise averages out;
            # at n=100 (< 2 full batches) short-text figures swing ~3x.
            n = 250 if args.quick else (600 if n_words < 250 else 300)
            per_1k = bench(model, n_words, n)
            est_20k = per_1k * 20  # seconds at the common CCR_MAX_ROWS=20000
            print(
                f"  {label:32s} {per_1k:8.1f} s/1k   "
                f"(20k rows ~ {est_20k / 60:5.1f} min)"
            )
        print()
        del model


if __name__ == "__main__":
    main()
