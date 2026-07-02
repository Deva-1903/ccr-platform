"""ORM models.

IDs are UUID strings (portable across SQLite/Postgres). JSON-ish payloads
(column lists, construct items, job metadata/summaries) are stored as JSON
text — they are read-mostly blobs, not queried relationally.
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


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
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
    reference: Mapped[str] = mapped_column(Text, default="")
    items_json: Mapped[str] = mapped_column(Text)  # list[str]
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id"))
    construct_id: Mapped[str] = mapped_column(ForeignKey("constructs.id"))
    text_column: Mapped[str] = mapped_column(String(200))
    model_name: Mapped[str] = mapped_column(String(200))
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
