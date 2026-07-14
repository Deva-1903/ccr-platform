"""Database setup - SQLite via SQLAlchemy.

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


def _sqlite_literal(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def auto_migrate_sqlite(target_engine, metadata) -> list[str]:
    """Add ORM columns missing from existing SQLite tables (additive only).

    create_all() creates missing tables but never alters existing ones, so a
    dev DB from last week 500s on this week's new column. This closes that gap
    for the additive changes we make; anything non-additive (renames, drops,
    type changes) waits for Alembic, which replaces this in Phase 2 alongside
    Postgres. Columns with scalar defaults get that default; callable defaults
    (uuid/now) are added nullable and filled by the ORM on new rows.
    """
    import logging

    from sqlalchemy import inspect, text

    added: list[str] = []
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
                    ddl += f" DEFAULT {_sqlite_literal(default)}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
    if added:
        logging.getLogger("ccr.db").warning("auto-migrated columns: %s", ", ".join(added))
    return added
