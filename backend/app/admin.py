"""Admin endpoints - the minimal operational surface (design: admin page v1).

Four concrete pains drive this, nothing speculative:
  * password resets ("reset = admin action" finally has an admin action),
  * per-user lab tier (replaces the global saved-run env hack: lab accounts
    get unlimited saved runs, public accounts keep the cap),
  * the RA's verification queue (mark constructs verified from the UI;
    the YAML library stays the durable source of truth - DB status is the
    operational overlay and is written back to YAML by the developer),
  * usage numbers + failed-run triage (the PI's "how is testing going?"
    answered with counts, and stuck runs requeued without SQL).

Access: signed-in AND email in the ADMIN_EMAILS env allowlist. Admin is an
env capability, not a DB role, so the DB cannot mint admins.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth, retention, storage
from . import jobs as jobs_module
from .db import get_db
from .models import Construct, Corpus, Job, Project, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(request: Request) -> dict:
    user = auth.get_current_user(request)
    if user is None or not auth.is_admin(user.get("email")):
        raise HTTPException(403, "Admin access required.")
    return user


# ---------------------------------------------------------------- overview
@router.get("/overview")
def overview(db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    runs_by_status = dict(
        db.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
    )
    return {
        "users": db.query(User).count(),
        "lab_users": db.query(User).filter_by(role="lab").count(),
        "projects": db.query(Project).count(),
        "anonymous_projects": db.query(Project).filter_by(owner_user_id="").count(),
        "corpora": db.query(Corpus).count(),
        "runs_total": db.query(Job).count(),
        "runs_by_status": runs_by_status,
        "runs_last_7_days": db.query(Job).filter(Job.created_at >= week_ago).count(),
        "signups_last_7_days": db.query(User).filter(User.created_at >= week_ago).count(),
        "constructs_unverified": db.query(Construct)
        .filter(Construct.verification_status != "verified")
        .filter_by(is_seed=True)
        .count(),
    }


# ------------------------------------------------------------------- users
@router.get("/users")
def list_users(db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    saved = dict(
        db.query(Project.owner_user_id, func.count(Job.id))
        .join(Job, Job.project_id == Project.id)
        .filter(Project.owner_user_id != "")
        .group_by(Project.owner_user_id)
        .all()
    )
    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "role": u.role or "member",
            "google_only": not u.password_hash,
            "saved_runs": saved.get(u.id, 0),
            "created_at": u.created_at,
            "is_admin": auth.is_admin(u.email),
        }
        for u in db.query(User).order_by(User.created_at.desc()).all()
    ]


@router.post("/users/{user_id}/role")
def set_role(
    user_id: str,
    body: dict,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    role = str(body.get("role", "")).strip().lower()
    if role not in ("member", "lab"):
        raise HTTPException(400, "Role must be 'member' or 'lab'.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    user.role = role
    db.commit()
    return {"id": user.id, "role": user.role}


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: str, db: Session = Depends(get_db), _admin: dict = Depends(require_admin)
):
    """Generate a temporary password, shown ONCE in the response. The admin
    passes it to the user, who should change it (or use Google sign-in)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    temp = secrets.token_urlsafe(9)  # 12 chars, meets the minimum length
    user.password_hash = auth.hash_password(temp)
    db.commit()
    return {"id": user.id, "email": user.email, "temporary_password": temp}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str, db: Session = Depends(get_db), admin: dict = Depends(require_admin)
):
    """Remove an account and everything it owns (files included)."""
    if user_id == admin["id"]:
        raise HTTPException(400, "You cannot delete your own admin account.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    for project in db.query(Project).filter_by(owner_user_id=user_id).all():
        retention.delete_project_cascade(db, project)
    db.delete(user)
    db.commit()
    return None


# ----------------------------------------------------------- failed runs
@router.get("/jobs/failed")
def failed_jobs(db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    rows = (
        db.query(Job)
        .filter(Job.status == "failed")
        .order_by(Job.created_at.desc())
        .limit(50)
        .all()
    )
    out = []
    for j in rows:
        corpus = db.get(Corpus, j.corpus_id)
        out.append(
            {
                "id": j.id,
                "created_at": j.created_at,
                "model_name": j.model_name,
                "language": j.language,
                "corpus_filename": corpus.filename if corpus else "",
                "corpus_file_available": bool(corpus and storage.exists(corpus.path)),
                "error_tail": (j.error or "").strip().splitlines()[-1] if j.error else "",
            }
        )
    return out


@router.post("/jobs/{job_id}/requeue")
def requeue_job(
    job_id: str, db: Session = Depends(get_db), _admin: dict = Depends(require_admin)
):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status != "failed":
        raise HTTPException(409, f"Only failed jobs can be requeued (status: {job.status}).")
    corpus = db.get(Corpus, job.corpus_id)
    if corpus is None or not storage.exists(corpus.path):
        raise HTTPException(
            410, "The corpus file is gone (anonymous retention); the run cannot be repeated."
        )
    job.status = "queued"
    job.error = ""
    job.progress = 0.0
    job.started_at = ""
    job.finished_at = ""
    db.commit()
    jobs_module.submit_job(job.id)
    return {"id": job.id, "status": "queued"}


# ------------------------------------------------------ verification queue
@router.get("/constructs")
def constructs_for_review(
    status: str = "",
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    q = db.query(Construct).filter_by(is_seed=True)
    if status:
        q = q.filter(Construct.verification_status == status)
    return [
        {
            "id": c.id,
            "name": c.name,
            "slug": c.construct_slug,
            "category": c.category or "",
            "n_items": len(json.loads(c.items_json)),
            "verification_status": c.verification_status or "draft",
            "reference": c.reference or "",
        }
        for c in q.order_by(Construct.name).all()
    ]


@router.post("/constructs/{construct_id}/verification")
def set_verification(
    construct_id: str,
    body: dict,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """Operational overlay for the RA's workflow. The YAML library remains the
    durable source of truth: statuses set here are exported and written back to
    the library files by the developer before production (recorded decision)."""
    status = str(body.get("status", "")).strip()
    if status not in ("verified", "needs_verification"):
        raise HTTPException(400, "Status must be 'verified' or 'needs_verification'.")
    construct = db.get(Construct, construct_id)
    if construct is None:
        raise HTTPException(404, "Construct not found")
    construct.verification_status = status
    db.commit()
    return {"id": construct.id, "verification_status": construct.verification_status}
