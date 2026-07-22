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

Access: signed-in AND (email in the ADMIN_EMAILS env allowlist, OR role
pi/maintainer - PI decision 2026-07-22). The app is self-governing: the
PI role carries escalation rights (grant/revoke staff, act on staff
accounts), maintainers get the operational surface only, and the env
allowlist is bootstrap + break-glass (seed the first PI; recover a
locked-out lab). Every mutating action lands in the admin_audit table.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth, retention, storage
from . import jobs as jobs_module
from .db import get_db
from .models import AdminAudit, Construct, Corpus, Invite, Job, Project, RoleAssignment, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(request: Request, db: Session = Depends(get_db)) -> dict:
    user = auth.get_current_user(request)
    if user is None:
        raise HTTPException(403, "Admin access required.")
    env_admin = auth.is_admin(user.get("email"))
    row = db.get(User, user["id"])
    role = auth.normalize_role(row.role if row else None)
    if not env_admin and not auth.role_is_staff(role):
        raise HTTPException(403, "Admin access required.")
    # can_escalate gates the power-expanding paths below (staff role grants,
    # actions on staff accounts): PIs and env-allowlisted admins have it,
    # maintainers get the operational surface only.
    return {
        **user,
        "role": role,
        "env_admin": env_admin,
        "can_escalate": env_admin or role == "pi",
    }


def _require_escalation_rights(admin: dict, target: User, action: str) -> None:
    """Actions on staff or env-allowlisted accounts require escalation rights
    (PI role or env allowlist) - otherwise a maintainer could take over a PI
    account (password reset), delete one, or mint more staff."""
    if admin["can_escalate"]:
        return
    if auth.role_is_staff(target.role) or auth.is_admin(target.email):
        raise HTTPException(
            403, f"Only a PI (or allowlisted admin) can {action} a PI/maintainer account."
        )


def _audit(db: Session, admin: dict, action: str, target: str, detail: str = "") -> None:
    """Append to the audit trail; committed together with the action itself."""
    db.add(AdminAudit(actor_email=admin.get("email", ""), action=action,
                      target=target, detail=detail))


# ---------------------------------------------------------------- overview
@router.get("/overview")
def overview(db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    runs_by_status = dict(
        db.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
    )
    users_by_role: dict[str, int] = {r: 0 for r in auth.ROLES}
    for (role,) in db.query(User.role).all():
        users_by_role[auth.normalize_role(role)] += 1
    return {
        "users": db.query(User).count(),
        "users_by_role": users_by_role,
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
            "role": auth.normalize_role(u.role),
            "google_only": not u.password_hash,
            "saved_runs": saved.get(u.id, 0),
            "created_at": u.created_at,
            "is_admin": auth.is_admin(u.email) or auth.role_is_staff(u.role),
            "env_admin": auth.is_admin(u.email),
        }
        for u in db.query(User).order_by(User.created_at.desc()).all()
    ]


@router.post("/users/{user_id}/role")
def set_role(
    user_id: str,
    body: dict,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    raw = str(body.get("role", "")).strip().lower()
    if raw not in auth.ROLES and raw != "member":  # "member" = legacy external
        raise HTTPException(400, f"Role must be one of: {', '.join(auth.ROLES)}.")
    role = auth.normalize_role(raw)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user_id == admin["id"]:
        raise HTTPException(400, "You cannot change your own role (ask another admin).")
    _require_escalation_rights(admin, user, "change the role of")
    if role in auth.STAFF_ROLES and not admin["can_escalate"]:
        raise HTTPException(403, "Only a PI (or allowlisted admin) can grant PI/maintainer roles.")
    old = auth.normalize_role(user.role)
    user.role = role
    _audit(db, admin, "set_role", user.email, f"{old} -> {role}")
    db.commit()
    return {"id": user.id, "role": user.role}


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: str, db: Session = Depends(get_db), admin: dict = Depends(require_admin)
):
    """Generate a temporary password, shown ONCE in the response. The admin
    passes it to the user, who should change it (or use Google sign-in)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    _require_escalation_rights(admin, user, "reset the password of")
    if not user.password_hash:
        raise HTTPException(
            400, "This is a Google account - it has no password to reset (they sign in via Google)."
        )
    temp = secrets.token_urlsafe(9)  # 12 chars, meets the minimum length
    user.password_hash = auth.hash_password(temp)
    _audit(db, admin, "reset_password", user.email)
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
    _require_escalation_rights(admin, user, "delete")
    for project in db.query(Project).filter_by(owner_user_id=user_id).all():
        retention.delete_project_cascade(db, project)
    _audit(db, admin, "delete_user", user.email, f"role was {auth.normalize_role(user.role)}")
    db.delete(user)
    db.commit()
    return None


# ---------------------------------------------------------------- invites
def _invite_out(inv: Invite) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    status = ("revoked" if inv.revoked_at
              else "expired" if inv.expires_at < today
              else "active")
    return {
        "id": inv.id,
        "role": auth.normalize_role(inv.role),
        "token": inv.token if status == "active" else "",  # only live links are copyable
        "created_by": inv.created_by,
        "created_at": inv.created_at,
        "expires_at": inv.expires_at,
        "status": status,
        "redemptions": json.loads(inv.redemptions_json or "[]"),
    }


@router.get("/invites")
def list_invites(db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    return [
        _invite_out(i)
        for i in db.query(Invite).order_by(Invite.created_at.desc()).limit(50).all()
    ]


@router.post("/invites", status_code=201)
def create_invite(
    body: dict,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Signed, expiring invite link: whoever registers through it lands at
    the invited tier (external/lab only - staff is granted, never invited).
    Backed by an Invite row, so it can be revoked early and shows who
    signed up through it."""
    role = str(body.get("role", "")).strip().lower()
    invite = Invite(id=uuid.uuid4().hex, role=auth.normalize_role(role),
                    token="", created_by=admin.get("email", ""), expires_at="")
    try:
        token, expires = auth.create_invite_token(role, admin.get("email", ""), invite.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    invite.token = token
    invite.expires_at = expires
    db.add(invite)
    _audit(db, admin, "invite_created", auth.normalize_role(role), f"expires {expires}")
    db.commit()
    # the creator always gets the token they just minted; the LIST endpoint
    # is what withholds tokens of expired/revoked links
    return {**_invite_out(invite), "token": token}


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(
    invite_id: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Soft revoke: the link stops working immediately; the row stays so
    history and redemptions remain visible."""
    invite = db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(404, "Invite not found")
    if not invite.revoked_at:
        invite.revoked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _audit(db, admin, "invite_revoked", auth.normalize_role(invite.role),
               f"created {invite.created_at[:10]} by {invite.created_by}")
        db.commit()
    return None


# ------------------------------------------------------ pre-assigned roles
@router.get("/role-assignments")
def list_role_assignments(db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    return [
        {"id": a.id, "email": a.email, "role": auth.normalize_role(a.role),
         "assigned_by": a.assigned_by, "created_at": a.created_at,
         "claimed_at": a.claimed_at or None}
        for a in db.query(RoleAssignment)
        .order_by(RoleAssignment.created_at.desc()).limit(100).all()
    ]


@router.post("/role-assignments", status_code=201)
def create_role_assignment(
    body: dict,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Bind a role to an email BEFORE the account exists: whoever first signs
    in with this email (password or Google) lands at this tier. This is how
    an external collaborator gets full credentials without touching env vars.
    Staff assignments require escalation rights, same as the Users table."""
    email = str(body.get("email", "")).strip().lower()
    role = auth.normalize_role(str(body.get("role", "")))
    if not auth.valid_email(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if str(body.get("role", "")).strip().lower() not in auth.ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(auth.ROLES)}.")
    if role in auth.STAFF_ROLES and not admin["can_escalate"]:
        raise HTTPException(403, "Only a PI (or allowlisted admin) can pre-assign PI/maintainer roles.")
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(409, "This email already has an account - change their role in the Users table.")
    existing = db.query(RoleAssignment).filter_by(email=email).first()
    if existing is not None:
        if auth.role_is_staff(existing.role) and not admin["can_escalate"]:
            raise HTTPException(403, "Only a PI (or allowlisted admin) can change a staff pre-assignment.")
        existing.role = role
        existing.assigned_by = admin.get("email", "")
        existing.claimed_at = ""
        assignment = existing
    else:
        assignment = RoleAssignment(email=email, role=role, assigned_by=admin.get("email", ""))
        db.add(assignment)
    _audit(db, admin, "role_preassigned", email, role)
    db.commit()
    return {"id": assignment.id, "email": email, "role": role}


@router.delete("/role-assignments/{assignment_id}", status_code=204)
def delete_role_assignment(
    assignment_id: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    assignment = db.get(RoleAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(404, "Assignment not found")
    if auth.role_is_staff(assignment.role) and not admin["can_escalate"]:
        raise HTTPException(403, "Only a PI (or allowlisted admin) can remove a staff pre-assignment.")
    _audit(db, admin, "preassignment_removed", assignment.email,
           auth.normalize_role(assignment.role))
    db.delete(assignment)
    db.commit()
    return None


# -------------------------------------------------------------- audit log
@router.get("/audit")
def audit_log(db: Session = Depends(get_db), admin: dict = Depends(require_admin)):
    """Top-down oversight is the PI's (and env admin's) view - maintainers
    work the operational cards but don't review each other's actions."""
    if not admin["can_escalate"]:
        raise HTTPException(403, "The audit trail is visible to PIs and allowlisted admins.")
    rows = db.query(AdminAudit).order_by(AdminAudit.at.desc(), AdminAudit.id.desc()).limit(100).all()
    return [
        {"at": r.at, "actor": r.actor_email, "action": r.action,
         "target": r.target, "detail": r.detail}
        for r in rows
    ]


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
    job_id: str, db: Session = Depends(get_db), admin: dict = Depends(require_admin)
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
    _audit(db, admin, "requeue_job", job.id[:8])
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
    admin: dict = Depends(require_admin),
):
    """Operational overlay for the RA's workflow. The YAML library remains the
    durable source of truth: statuses set here are exported and written back to
    the library files by the developer before production (recorded decision).

    Verification is the MAINTAINER's job (PI decision 2026-07-22): the queue is
    visible to all staff, but only maintainers mark scales - the trail then
    shows the responsible RA, not whichever admin clicked. PI/env admins keep
    read access; to verify, hold the maintainer role."""
    if admin["role"] != "maintainer":
        raise HTTPException(
            403, "Construct verification is done by maintainers. "
                 "PI/admin accounts have read access to the queue."
        )
    status = str(body.get("status", "")).strip()
    if status not in ("verified", "needs_verification"):
        raise HTTPException(400, "Status must be 'verified' or 'needs_verification'.")
    construct = db.get(Construct, construct_id)
    if construct is None:
        raise HTTPException(404, "Construct not found")
    construct.verification_status = status
    _audit(db, admin, "set_verification", construct.name, status)
    db.commit()
    return {"id": construct.id, "verification_status": construct.verification_status}
