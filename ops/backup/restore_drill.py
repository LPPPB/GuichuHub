"""Restore a custom dump into an explicitly named disposable database."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def restore_drill(database_url_file: Path, dump_file: Path, temporary_database: str) -> None:
    """Create, restore, and inspect a temporary database; never alters the source DB."""
    if not temporary_database.startswith("kichu_restore_drill_"):
        raise ValueError("temporary database name must start with kichu_restore_drill_")
    url = make_url(database_url_file.read_text(encoding="utf-8").strip())
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL database URL is required")
    environment = {"PGHOST": str(url.host), "PGPORT": str(url.port or 5432), "PGUSER": str(url.username),
                   "PGPASSWORD": str(url.password), "PGDATABASE": "postgres"}
    subprocess.run(["createdb", temporary_database], env={**os.environ, **environment}, check=True)
    try:
        subprocess.run(["pg_restore", "--dbname", temporary_database, str(dump_file)], env={**os.environ, **environment}, check=True)
        drill_url = url.set(database=temporary_database)
        with create_engine(drill_url).connect() as connection:
            connection.execute(text("SELECT version_num FROM app.alembic_version")).scalar_one()
            connection.execute(text("SELECT 1 FROM app.dashboard_state LIMIT 1"))
    finally:
        subprocess.run(["dropdb", "--if-exists", temporary_database], env={**os.environ, **environment}, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore a PostgreSQL backup into a disposable database")
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--dump", required=True, type=Path)
    parser.add_argument("--temporary-database", required=True)
    args = parser.parse_args()
    restore_drill(args.database_url_file, args.dump, args.temporary_database)
