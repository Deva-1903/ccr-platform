"""Database setup - SQLite (local dev) or PostgreSQL (deployments).

Backend chosen by DATABASE_URL:
  * unset            -> SQLite file under CCR_DATA_DIR (local dev; zero setup),
  * postgres URL     -> PostgreSQL (Supabase free tier recommended: persistent,
                        backed up, and already the auth provider - one vendor).

The models use no backend-specific features, so this is a connection-string
change, not a rewrite. On the ephemeral-disk hosts (HF Spaces free), SQLite is
wiped on every restart; Postgres is what makes accounts and data survive.

DATA_DIR still holds corpora/results/cache files locally; for durable FILE
storage on ephemeral hosts, additionally set CCR_STORAGE=s3 (storage.py).
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(
    os.environ.get("CCR_DATA_DIR", Path(__file__).resolve().parent.parent / "data")
)
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "corpora").mkdir(exist_ok=True)
(DATA_DIR / "results").mkdir(exist_ok=True)


def _normalize_pg_url(url: str) -> str:
    """Force the psycopg (v3) driver; accept the bare postgres:// URL that
    dashboards (Supabase) hand out."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_POSTGRES = _DATABASE_URL.startswith(("postgres://", "postgresql://"))

if IS_POSTGRES:
    engine = create_engine(
        _normalize_pg_url(_DATABASE_URL),
        pool_pre_ping=True,   # survive Supabase idle-connection drops
        pool_recycle=1800,
        pool_size=5,
        max_overflow=5,
    )
else:
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


def _default_literal(value, dialect_name: str) -> str:
    if isinstance(value, bool):
        if dialect_name == "postgresql":
            return "TRUE" if value else "FALSE"
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def auto_migrate_sqlite(target_engine, metadata) -> list[str]:
    """Add ORM columns missing from existing tables (additive only).

    Named for history; runs on both backends. create_all() creates missing
    tables but never alters existing ones, so a DB from last week 500s on this
    week's new column. This closes that gap for additive changes; anything
    non-additive (renames, drops, type changes) waits for Alembic. Columns with
    scalar defaults get that default; callable defaults (uuid/now) are added
    nullable and filled by the ORM on new rows. A brand-new Postgres database
    needs none of this (create_all already made every current column).
    """
    import logging

    from sqlalchemy import inspect, text

    added: list[str] = []
    dialect = target_engine.dialect.name
    inspector = inspect(target_engine)
    with target_engine.begin() as conn:
        for table in metadata.sorted_tables:
            if table.name not in inspector.get_table_names():
                continue  # create_all handles brand-new tables
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(target_engine.dialect)
                ddl = f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}'
                default = getattr(column.default, "arg", None)
                if default is not None and not callable(default):
                    ddl += f" DEFAULT {_default_literal(default, dialect)}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
    if added:
        logging.getLogger("ccr.db").warning("auto-migrated columns: %s", ", ".join(added))
    return added
