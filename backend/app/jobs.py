"""Background job runner.

Jobs run on a dedicated single-worker executor - a deliberate right-sizing:
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

import hashlib
import json
import logging
import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np

from . import registry, warnings_engine
from .ccr import FAKE_MODEL_NAME, get_backend, run_ccr
from .construct_lib import construct_snapshot
from .db import DATA_DIR, SessionLocal
from .ingest import load_corpus
from .models import Construct, Corpus, Job, Project
from .reproducibility import record_environment
from .retention import EMB_CACHE_DIR, remove_corpus_files
from . import storage

PLATFORM_VERSION = "0.2.0"
OUTPUT_SCHEMA_VERSION = "1.0"  # bump on ANY export-column change (CLAUDE.md hard rule)

logger = logging.getLogger("ccr.jobs")

RESULTS_DIR = DATA_DIR / "results"
HIST_BINS = 12
TOP_N = 10
SNIPPET_LEN = 220

# Single worker: sequential jobs, bounded memory. See module docstring.
# Created lazily and re-creatable: a lifespan shutdown (dev reload, test
# client closing) must not permanently kill job submission for the process.
import threading

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccr-job")
        return _executor


def submit_job(job_id: str) -> None:
    _get_executor().submit(_run_job_logged, job_id)


def shutdown_executor() -> None:
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None


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

        # Materialize the corpus locally (a no-op on the local backend; a
        # temp download when files live in object storage).
        local_corpus, corpus_is_temp = storage.fetch_to_local(corpus.path)
        try:
            df, _ = load_corpus(str(local_corpus))
        finally:
            if corpus_is_temp:
                local_corpus.unlink(missing_ok=True)
        if job.text_column not in df.columns:
            raise ValueError(f"Column '{job.text_column}' not found in corpus.")

        texts_all = df[job.text_column].astype("string")
        mask = texts_all.notna() & (texts_all.str.strip() != "")
        dropped = int((~mask).sum())
        work_df = df.loc[mask].reset_index(drop=True)
        texts = work_df[job.text_column].astype(str).tolist()

        last_progress = -1.0

        def progress(frac: float):
            # Throttled: commit only on >=1% movement (or completion) so large
            # corpora don't turn the progress bar into a DB write hotspot.
            nonlocal last_progress
            frac = round(float(frac), 3)
            if frac - last_progress >= 0.01 or frac >= 1.0:
                last_progress = frac
                _set(db, job, progress=frac)

        # Model config from the registry (spec 0003); the test fake has none.
        model_cfg = None if job.model_name == FAKE_MODEL_NAME else registry.get_model(job.model_name)
        item_prefix = model_cfg.item_prefix if (model_cfg and model_cfg.requires_prefix) else ""
        text_prefix = model_cfg.text_prefix if (model_cfg and model_cfg.requires_prefix) else ""

        project = db.get(Project, job.project_id)
        is_anonymous = not (project and project.owner_user_id)

        # Corpus-embedding cache: the CCR workflow is many constructs against
        # the SAME corpus, and ~97% of a run is embedding the documents. Corpora
        # are immutable after upload, so (corpus, column, model, revision,
        # prefix) fully determines the embeddings - reusing them is bit-identical.
        # Disabled for the test fake (unless forced) and skipped for anonymous
        # runs (their files are removed right after the run anyway).
        cache_enabled = os.environ.get("CCR_EMB_CACHE", "1") == "1" and (
            model_cfg is not None or os.environ.get("CCR_EMB_CACHE_FORCE") == "1"
        )
        cache_path = None
        cached_embeddings = None
        if cache_enabled:
            key = hashlib.sha256(
                f"{job.text_column}|{job.model_name}|"
                f"{model_cfg.revision if model_cfg else 'fake'}|{text_prefix}".encode()
            ).hexdigest()[:20]
            cache_path = EMB_CACHE_DIR / f"{corpus.id}_{key}.npy"
            if cache_path.exists():
                try:
                    candidate = np.load(cache_path)
                    if candidate.shape[0] == len(texts):
                        cached_embeddings = candidate
                except Exception:
                    cache_path.unlink(missing_ok=True)  # unreadable cache: recompute

        backend = get_backend(job.model_name)
        result = run_ccr(
            texts, items, backend,
            progress_cb=progress, item_prefix=item_prefix, text_prefix=text_prefix,
            doc_embeddings=cached_embeddings,
        )
        if (
            cache_enabled and cache_path is not None and cached_embeddings is None
            and not is_anonymous and result.doc_embeddings is not None
        ):
            try:
                np.save(cache_path, result.doc_embeddings)
            except Exception:
                logger.warning("could not write embedding cache %s", cache_path)

        # Structured data-quality warnings (spec 0001) - objects, never bare strings.
        W = warnings_engine.warning
        warnings: list[dict] = []
        if dropped:
            warnings.append(W(
                "EMPTY_ROWS_DROPPED", "info",
                f"{dropped} empty text row(s) were dropped before analysis.", count=dropped,
            ))
        n_dupes = len(texts) - len(set(texts))
        if n_dupes:
            warnings.append(W(
                "DUPLICATE_TEXTS", "warning",
                f"{n_dupes} duplicate text(s) detected - each is scored independently; "
                "deduplicate upstream if unintended.", count=n_dupes,
            ))
        short = warnings_engine.short_text_warning(texts)
        if short:
            warnings.append(short)
        max_seq = model_cfg.max_seq_length if model_cfg else result.metadata.get("model_max_seq_length")
        if max_seq:
            char_budget = int(max_seq) * 4  # rough chars-per-token heuristic
            n_long = sum(1 for t in texts if len(t) > char_budget)
            if n_long:
                warnings.append(W(
                    "TEXTS_MAYBE_TRUNCATED", "warning",
                    f"{n_long} text(s) likely exceed the model's {max_seq}-token window and "
                    "were truncated; consider splitting long documents.", count=n_long,
                ))
        if parse_info.get("note"):
            warnings.append(W("ENCODING_FALLBACK", "warning", parse_info["note"]))

        # Language checks: corpus-level detection + model-coverage (spec 0001, design §12).
        selected_language = (job.language or "en").lower()
        lang_result, lang_warnings = warnings_engine.detect_corpus_language(texts, selected_language)
        warnings.extend(lang_warnings)
        if model_cfg:
            mlw = warnings_engine.model_language_warning(
                selected_language, model_cfg.id, model_cfg.supported_languages,
                model_cfg.language_set_name,
            )
            if mlw:
                warnings.append(mlw)
        for user_warning in (model_cfg.user_warnings if model_cfg else ()):
            warnings.append(W("MODEL_NOTE", "info", user_warning))

        # Export mirrors ccr_wrapper's shape: input columns + per-item
        # similarity columns + overall score, so it drops into existing
        # CCR workflows.
        out = work_df.copy()
        for j in range(result.similarities.shape[1]):
            out[f"sim_item_{j + 1}"] = np.round(result.similarities[:, j], 6)
        out["ccr_score"] = np.round(result.scores, 6)
        local_result = RESULTS_DIR / f"{job.id}.csv"
        out.to_csv(local_result, index=False)
        result_path = storage.move_local_into_storage("results", f"{job.id}.csv", local_result)

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
            "platform_version": PLATFORM_VERSION,
            "output_schema_version": OUTPUT_SCHEMA_VERSION,
            "corpus_file": corpus.filename,
            "corpus_parse_info": parse_info,
            "text_column": job.text_column,
            "language": lang_result.as_metadata(),
            "construct": construct.name,
            "construct_reference": construct.reference,
            "construct_snapshot": construct_snapshot(construct),
            "model_registry_id": model_cfg.id if model_cfg else job.model_name,
            "provider_model_id": model_cfg.provider_model_id if model_cfg else job.model_name,
            "model_revision": model_cfg.revision if model_cfg else None,
            "model_pooling_fallback": model_cfg.pooling_fallback if model_cfg else None,
            "model_max_seq_length": model_cfg.max_seq_length if model_cfg else None,
            "scoring": {"adjustment_strategy": "none", "aggregate": "mean_all_items"},
            "output_schema": (
                list(work_df.columns)
                + [f"sim_item_{j + 1}" for j in range(result.similarities.shape[1])]
                + ["ccr_score"]
            ),
            "warnings": warnings,
            "n_rows_input": int(corpus.n_rows),
            "n_rows_dropped_empty": dropped,
        }
        record_environment(metadata)  # pins exact package versions for the repro bundle

        # Retention (PI decision 2026-07-10): anonymous uploads are removed the
        # moment analysis finishes. The results summary/CSV stay downloadable
        # until the anonymous project's TTL purge; the raw upload does not.
        if is_anonymous:
            remove_corpus_files(corpus)
            corpus.path = ""
            metadata["anonymous_corpus_removed"] = True
            warnings.append(W(
                "ANONYMOUS_DATA_REMOVED", "info",
                "The uploaded file was deleted after this analysis (anonymous runs "
                "keep no raw data). Re-running requires uploading again, or sign in "
                "to keep datasets.",
            ))
            summary["warnings"] = warnings
            metadata["warnings"] = warnings

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
