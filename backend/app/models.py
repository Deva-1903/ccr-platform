"""ORM models.

IDs are UUID strings (portable across SQLite/Postgres). JSON-ish payloads
(column lists, construct items, job metadata/summaries) are stored as JSON
text - they are read-mostly blobs, not queried relationally.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(Text)  # scrypt$salt$digest (auth.py)
    role: Mapped[str] = mapped_column(String(16), default="external")
    # external | lab | maintainer | pi (auth.ROLES; legacy "member" reads as
    # external). lab+ = unlimited saved runs; maintainer/pi also get /admin.
    # Staff roles are grantable only by ADMIN_EMAILS env-allowlisted admins
    # (admin.py guards), so the API cannot self-escalate; the env allowlist
    # remains the bootstrap and break-glass admin path.
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class RoleAssignment(Base):
    """Pre-provisioned access: a role bound to an email BEFORE the account
    exists (PI request 2026-07-22 - e.g. an external collaborator who must
    land with full credentials on first sign-in, Google or password).

    Unlike invite links (bearer tokens, external/lab only), assignments are
    email-bound and may carry staff roles - so creating one for pi/maintainer
    requires escalation rights. Claimed rows are kept as history."""

    __tablename__ = "role_assignments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16))
    assigned_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    claimed_at: Mapped[str] = mapped_column(String(32), default="")  # "" = pending


class Invite(Base):
    """Invite links, stateful so they can be listed, revoked, and traced.

    The signed token (auth.py) still proves authenticity, but redemption
    requires this row to be live: not revoked, not expired. Revocation is
    soft (revoked_at) so history and redemptions stay visible. Redemptions
    are a read-mostly JSON list [{email, at}], per the repo's JSON-blob
    convention."""

    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    role: Mapped[str] = mapped_column(String(16))
    token: Mapped[str] = mapped_column(Text)  # stored so admins can re-copy the link
    created_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    expires_at: Mapped[str] = mapped_column(String(32))  # ISO date, inclusive
    revoked_at: Mapped[str] = mapped_column(String(32), default="")  # "" = active
    redemptions_json: Mapped[str] = mapped_column(Text, default="[]")


class AdminAudit(Base):
    """Append-only trail of admin actions (who did what to whom, when).

    What makes multiple admins trustworthy: role grants, password resets,
    deletions, invites, requeues, and verification changes all land here.
    Never updated or deleted from the app."""

    __tablename__ = "admin_audit"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    at: Mapped[str] = mapped_column(String(32), default=_now)
    actor_email: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(40))  # e.g. set_role, invite_created
    target: Mapped[str] = mapped_column(String(300), default="")  # email/name acted on
    detail: Mapped[str] = mapped_column(Text, default="")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_user_id: Mapped[str] = mapped_column(String(32), default="")  # "" = anonymous
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class Corpus(Base):
    __tablename__ = "corpora"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    filename: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(Text)
    n_rows: Mapped[int] = mapped_column()
    columns_json: Mapped[str] = mapped_column(Text)  # list[str]
    parse_info_json: Mapped[str] = mapped_column(Text, default="{}")  # how the file was parsed
    suggested_text_column: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class Construct(Base):
    __tablename__ = "constructs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    reference: Mapped[str] = mapped_column(Text, default="")  # citation
    items_json: Mapped[str] = mapped_column(Text)  # list[str]
    reverse_flags_json: Mapped[str] = mapped_column(Text, default="[]")  # list[bool], parallel to items
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Library identity (spec 0004): versioned append-only; hash via reference algorithm.
    construct_slug: Mapped[str] = mapped_column(String(120), default="")
    version: Mapped[int] = mapped_column(default=1)
    item_hash: Mapped[str] = mapped_column(String(64), default="")
    verification_status: Mapped[str] = mapped_column(String(24), default="draft")
    # draft | needs_verification | verified | archived
    language: Mapped[str] = mapped_column(String(12), default="en")
    category: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id"))
    construct_id: Mapped[str] = mapped_column(ForeignKey("constructs.id"))
    # Multi-construct runs: the full ordered id list. construct_id stays the
    # first entry (FK + legacy rows, whose "[]" here means "just construct_id").
    construct_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    text_column: Mapped[str] = mapped_column(String(200))
    model_name: Mapped[str] = mapped_column(String(200))  # registry id (or test fake)
    language: Mapped[str] = mapped_column(String(12), default="en")  # selected analysis language
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # queued -> running -> completed | failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    error: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")  # reproducibility record
    summary_json: Mapped[str] = mapped_column(Text, default="{}")  # results summary
    result_path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    started_at: Mapped[str] = mapped_column(String(32), default="")
    finished_at: Mapped[str] = mapped_column(String(32), default="")
