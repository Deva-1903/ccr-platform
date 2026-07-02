"""Database setup — SQLite via SQLAlchemy.

SQLite is a deliberate choice for this deployment size (single-node, few
concurrent writers). The models use no SQLite-specific features, so moving
to PostgreSQL when multi-user concurrency arrives is a connection-string
change plus a migration, not a rewrite.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# CCR_DATA_DIR overrides where the DB, corpora, and results live
# (used by tests to keep runs isolated; useful for deployments too).
DATA_DIR = Path(
    os.environ.get("CCR_DATA_DIR", Path(__file__).resolve().parent.parent / "data")
)
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "corpora").mkdir(exist_ok=True)
(DATA_DIR / "results").mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "ccr.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},  # FastAPI threadpool access
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """WAL lets the API read while the job worker writes; busy_timeout
    absorbs brief lock contention instead of raising immediately."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
