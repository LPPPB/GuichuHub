"""Restore a custom dump into an explicitly named disposable database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def _environment(url, *, database: str) -> dict[str, str]:
    return {"PGHOST": str(url.host), "PGPORT": str(url.port or 5432), "PGUSER": str(url.username),
            "PGPASSWORD": str(url.password), "PGDATABASE": database}


def _verified_manifest(dump_file: Path, manifest_file: Path) -> dict:
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if not manifest.get("alembic_revision"):
        raise ValueError("backup manifest has no Alembic revision")
    expected = manifest.get("sha256")
    actual = hashlib.sha256(dump_file.read_bytes()).hexdigest()
    if not expected or actual != expected:
        raise ValueError("backup dump checksum does not match manifest")
    return manifest


def restore_drill(database_url_file: Path, dump_file: Path, temporary_database: str, *,
                  provisioner_database_url_file: Path, manifest_file: Path) -> None:
    """Create, restore, and inspect a temporary database; never alters the source DB."""
    if not temporary_database.startswith("kichu_restore_drill_"):
        raise ValueError("temporary database name must start with kichu_restore_drill_")
    manifest = _verified_manifest(dump_file, manifest_file)
    restore_url = make_url(database_url_file.read_text(encoding="utf-8").strip())
    provisioner_url = make_url(provisioner_database_url_file.read_text(encoding="utf-8").strip())
    if restore_url.get_backend_name() != "postgresql" or provisioner_url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL database URL is required")
    if not restore_url.username:
        raise ValueError("restore database URL must name the migration role")
    provisioner_environment = _environment(provisioner_url, database="postgres")
    restore_environment = _environment(restore_url, database=temporary_database)
    created = False
    try:
        subprocess.run(["createdb", "--owner", restore_url.username, temporary_database],
                       env={**os.environ, **provisioner_environment}, check=True)
        created = True
        subprocess.run(["pg_restore", "--dbname", temporary_database, str(dump_file)],
                       env={**os.environ, **restore_environment}, check=True)
        drill_url = restore_url.set(database=temporary_database)
        with create_engine(drill_url).connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM app.alembic_version")).scalar_one()
            if revision != manifest["alembic_revision"]:
                raise RuntimeError("restored Alembic revision does not match backup manifest")
            connection.execute(text("SELECT 1 FROM app.dashboard_state LIMIT 1"))
    finally:
        if created:
            subprocess.run(["dropdb", "--if-exists", "--force", temporary_database],
                           env={**os.environ, **provisioner_environment}, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore a PostgreSQL backup into a disposable database")
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--provisioner-database-url-file", required=True, type=Path)
    parser.add_argument("--dump", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--temporary-database", required=True)
    args = parser.parse_args()
    restore_drill(args.database_url_file, args.dump, args.temporary_database,
                  provisioner_database_url_file=args.provisioner_database_url_file,
                  manifest_file=args.manifest)
