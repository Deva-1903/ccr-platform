"""Additive SQLite auto-migration: an old-schema DB gains new ORM columns
at startup instead of 500ing (the 'no such column: projects.archived' bug)."""

import sqlite3

from sqlalchemy import create_engine, inspect

from app.db import Base, auto_migrate_sqlite
from app.models import Project  # noqa: F401 - registers tables on Base.metadata


def test_old_schema_gains_missing_columns(tmp_path):
    db_path = tmp_path / "old.db"

    # Simulate a dev DB created before archived/language/etc. existed.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE projects (id VARCHAR(32) PRIMARY KEY, name VARCHAR(200), "
        "description TEXT, created_at VARCHAR(32))"
    )
    conn.execute(
        "INSERT INTO projects VALUES ('abc123', 'Old Project', '', '2026-07-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)  # creates the other, brand-new tables
    added = auto_migrate_sqlite(engine, Base.metadata)

    assert "projects.archived" in added
    cols = {c["name"] for c in inspect(engine).get_columns("projects")}
    assert "archived" in cols

    # Existing row survives with the default applied, and queries work.
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT name, archived FROM projects WHERE id='abc123'").fetchone()
    conn.close()
    assert row == ("Old Project", 0)

    # Second run is a no-op (idempotent).
    assert auto_migrate_sqlite(engine, Base.metadata) == []
