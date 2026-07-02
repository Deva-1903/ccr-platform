"""Background job runner.

Jobs run on a dedicated single-worker executor — a deliberate right-sizing:
embedding is CPU-bound, so running jobs sequentially protects the instance's
memory and keeps per-job throughput predictable, while job state lives in
the DB (queued → running → completed/failed) so the API and UI never depend
on in-process state. The upgrade trigger to Celery + Redis is multi-instance
deployment or retry semantics; because state is already externalized, that
swap changes this module only, not the API contract.

Startup recovery: any job left 'queued'/'running' by a previous process
(deploy, crash, restart) is marked failed with an explanatory message
rather than hanging forever in the UI.
"""

from __future__ import annotations

import json
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np

from .ccr import get_backend, run_ccr
from .db import DATA_DIR, SessionLocal
from .ingest import load_corpus
from .models import Construct, Corpus, Job

logger = logging.getLogger("ccr.jobs")

RESULTS_DIR = DATA_DIR / "results"
HIST_BINS = 12
TOP_N = 10
SNIPPET_LEN = 220

# Single worker: sequential jobs, bounded memory. See module docstring.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccr-job")


def submit_job(job_id: str) -> None:
    _executor.submit(_run_job_logged, job_id)


def shutdown_executor() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)


def recover_orphaned_jobs() -> int:
    """Fail jobs orphaned by a previous process so they don't hang in the UI."""
    db = SessionLocal()
    try:
        orphans = db.query(Job).filter(Job.status.in_(["queued", "running"])).all()
        for job in orphans:
            job.status = "failed"
            job.error = (
                "Interrupted by a server restart before completion. "
                "Please run the analysis again."
            )
            job.finished_at = _now()
        db.commit()
        if orphans:
            logger.warning("Recovered %d orphaned job(s) from previous run", len(orphans))
        return len(orphans)
    finally:
        db.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _set(db, job: Job, **kw):
    for k, v in kw.items():
        setattr(job, k, v)
    db.commit()


def _run_job_logged(job_id: str) -> None:
    try:
        run_job(job_id)
    except Exception:  # last-resort guard: a worker thread must never die silently
        logger.exception("Unhandled error in job %s", job_id)


def run_job(job_id: str) -> None:
    """Execute one CCR job; all state transitions are persisted to the DB."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        _set(db, job, status="running", started_at=_now(), progress=0.0)
        logger.info("Job %s started (model=%s)", job_id[:8], job.model_name)

        corpus = db.get(Corpus, job.corpus_id)
        construct = db.get(Construct, job.construct_id)
        items = json.loads(construct.items_json)
        parse_info = json.loads(corpus.parse_info_json or "{}")

        df, _ = load_corpus(corpus.path)
        if job.text_column not in df.columns:
            raise ValueError(f"Column '{job.text_column}' not found in corpus.")

        texts_all = df[job.text_column].astype("string")
        mask = texts_all.notna() & (texts_all.str.strip() != "")
        dropped = int((~mask).sum())
        work_df = df.loc[mask].reset_index(drop=True)
        texts = work_df[job.text_column].astype(str).tolist()

        def progress(frac: float):
            _set(db, job, progress=round(float(frac), 3))

        backend = get_backend(job.model_name)
        result = run_ccr(texts, items, backend, progress_cb=progress)

        # Data-quality warnings surfaced to the researcher, not buried in logs.
        warnings = []
        if dropped:
            warnings.append(f"{dropped} empty text row(s) were dropped before analysis.")
        n_dupes = len(texts) - len(set(texts))
        if n_dupes:
            warnings.append(
                f"{n_dupes} duplicate text(s) detected — each is scored "
                "independently; deduplicate upstream if unintended."
            )
        max_seq = result.metadata.get("model_max_seq_length")
        if max_seq:
            char_budget = int(max_seq) * 4  # rough chars-per-token heuristic
            n_long = sum(1 for t in texts if len(t) > char_budget)
            if n_long:
                warnings.append(
                    f"{n_long} text(s) likely exceed the model's {max_seq}-token "
                    "window and were truncated; consider splitting long documents."
                )
        if parse_info.get("note"):
            warnings.append(parse_info["note"])

        # Export mirrors ccr_wrapper's shape: input columns + per-item
        # similarity columns + overall score, so it drops into existing
        # CCR workflows.
        out = work_df.copy()
        for j in range(result.similarities.shape[1]):
            out[f"sim_item_{j + 1}"] = np.round(result.similarities[:, j], 6)
        out["ccr_score"] = np.round(result.scores, 6)
        result_path = RESULTS_DIR / f"{job.id}.csv"
        out.to_csv(result_path, index=False)

        scores = result.scores
        order = np.argsort(scores)
        hist_counts, hist_edges = np.histogram(scores, bins=HIST_BINS)

        def doc_entry(i: int) -> dict:
            return {
                "row": int(i),
                "score": round(float(scores[i]), 4),
                "text": texts[i][:SNIPPET_LEN] + ("…" if len(texts[i]) > SNIPPET_LEN else ""),
            }

        summary = {
            "n_docs": len(texts),
            "n_dropped_empty": dropped,
            "warnings": warnings,
            "score_mean": round(float(scores.mean()), 4),
            "score_sd": round(float(scores.std(ddof=1)), 4) if len(scores) > 1 else 0.0,
            "score_min": round(float(scores.min()), 4),
            "score_max": round(float(scores.max()), 4),
            "histogram": {
                "counts": hist_counts.tolist(),
                "edges": [round(float(e), 4) for e in hist_edges],
            },
            "item_means": [
                {"item": items[j], "mean": round(float(result.similarities[:, j].mean()), 4)}
                for j in range(len(items))
            ],
            "top_docs": [doc_entry(i) for i in order[::-1][:TOP_N]],
            "bottom_docs": [doc_entry(i) for i in order[:TOP_N]],
        }

        metadata = {
            **result.metadata,
            "job_id": job.id,
            "corpus_file": corpus.filename,
            "corpus_parse_info": parse_info,
            "text_column": job.text_column,
            "construct": construct.name,
            "construct_reference": construct.reference,
            "n_rows_input": int(corpus.n_rows),
            "n_rows_dropped_empty": dropped,
        }

        _set(
            db,
            job,
            status="completed",
            progress=1.0,
            finished_at=_now(),
            result_path=str(result_path),
            summary_json=json.dumps(summary),
            metadata_json=json.dumps(metadata),
        )
        logger.info(
            "Job %s completed: %d texts in %ss",
            job_id[:8],
            len(texts),
            result.metadata["duration_seconds"],
        )
    except Exception:
        logger.exception("Job %s failed", job_id[:8])
        job = db.get(Job, job_id)
        if job is not None:
            _set(db, job, status="failed", error=traceback.format_exc(limit=3), finished_at=_now())
    finally:
        db.close()
