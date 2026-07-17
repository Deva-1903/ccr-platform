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
    role: Mapped[str] = mapped_column(String(16), default="member")  # member | lab
    # "lab" = unlimited saved runs (set via /admin). Admins are NOT a DB role:
    # admin access is granted by the ADMIN_EMAILS env allowlist (auth.is_admin).
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


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
