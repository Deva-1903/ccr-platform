"""Data retention (PI decision, 2026-07-10: "remove temp data after analysis").

Policy:
  * ANONYMOUS runs: the uploaded corpus file (and its embedding cache) is
    deleted the moment the run finishes (jobs.py calls remove_corpus_files).
    Result summaries/CSVs stick around so the person can download them, then
    the whole anonymous project is purged after CCR_ANON_TTL_HOURS.
  * SIGNED-IN runs: nothing is auto-deleted; a saved-run cap applies instead
    (enforced at job creation in main.py - the user chooses what to delete).

The purge loop runs in a daemon thread (startup + hourly). TTL of 0 disables
purging entirely - the local-dev default, so nobody's dev projects vanish
overnight. Deployments set CCR_ANON_TTL_HOURS=24.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from . import auth, storage
from .db import DATA_DIR, SessionLocal
from .models import Corpus, Job, Project

logger = logging.getLogger("ccr.retention")

EMB_CACHE_DIR = DATA_DIR / "emb_cache"
EMB_CACHE_DIR.mkdir(exist_ok=True)

_stop = threading.Event()
_thread: threading.Thread | None = None


def remove_corpus_files(corpus: Corpus) -> None:
    """Delete the uploaded file (whatever backend holds it) and any cached
    embeddings (always local - caches are derived data)."""
    storage.delete(corpus.path)
    for cached in EMB_CACHE_DIR.glob(f"{corpus.id}_*.npy"):
        cached.unlink(missing_ok=True)


def delete_project_cascade(db: Session, project: Project) -> dict:
    """Shared cascade used by the DELETE endpoint and the anonymous purge.
    Removes DB rows plus uploaded, result, and embedding-cache files. Logs
    counts only - never any uploaded text (design doc §9)."""
    corpora = db.query(Corpus).filter_by(project_id=project.id).all()
    jobs = db.query(Job).filter_by(project_id=project.id).all()

    for corpus in corpora:
        remove_corpus_files(corpus)
    for job in jobs:
        storage.delete(job.result_path)

    for job in jobs:
        db.delete(job)
    for corpus in corpora:
        db.delete(corpus)
    db.delete(project)
    db.commit()
    return {"corpora": len(corpora), "runs": len(jobs)}


def purge_expired_anonymous(db: Session) -> int:
    """Delete anonymous projects whose last activity is older than the TTL."""
    ttl = auth.anon_ttl_hours()
    if ttl <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl)).isoformat(timespec="seconds")

    purged = 0
    candidates = db.query(Project).filter(Project.owner_user_id == "").all()
    for project in candidates:
        latest_job = (
            db.query(Job.created_at)
            .filter_by(project_id=project.id)
            .order_by(Job.created_at.desc())
            .first()
        )
        last_activity = max(project.created_at, latest_job[0]) if latest_job else project.created_at
        if last_activity < cutoff:
            counts = delete_project_cascade(db, project)
            purged += 1
            logger.info(
                "purged expired anonymous project id=%s (corpora=%d runs=%d, ttl=%dh)",
                project.id, counts["corpora"], counts["runs"], ttl,
            )
    return purged


def _loop(interval_seconds: int) -> None:
    while not _stop.wait(interval_seconds):
        db = SessionLocal()
        try:
            purge_expired_anonymous(db)
        except Exception:
            logger.exception("anonymous purge failed; will retry next cycle")
        finally:
            db.close()


def start_cleanup(interval_seconds: int = 3600) -> None:
    """Run one purge now, then hourly in a daemon thread. No-op if TTL is 0."""
    global _thread
    db = SessionLocal()
    try:
        purge_expired_anonymous(db)
    except Exception:
        logger.exception("startup anonymous purge failed")
    finally:
        db.close()
    if auth.anon_ttl_hours() > 0 and (_thread is None or not _thread.is_alive()):
        _stop.clear()
        _thread = threading.Thread(target=_loop, args=(interval_seconds,), daemon=True,
                                   name="ccr-retention")
        _thread.start()


def stop_cleanup() -> None:
    _stop.set()
