"""Create and verify a PostgreSQL custom-format backup without logging secrets."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def create_postgres_backup(*, runner, destination_dir: Path, connection: dict,
                           revision: str, git_tag: str, image_digest: str) -> dict:
    """Run ``pg_dump --format=custom``, verify its catalog, and write a manifest."""
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_name = f"kichu_postgres_{timestamp}.dump"
    dump_path = destination_dir / dump_name
    environment = {
        "PGHOST": str(connection["host"]), "PGPORT": str(connection.get("port", "5432")),
        "PGUSER": str(connection["user"]), "PGPASSWORD": str(connection["password"]),
        "PGDATABASE": str(connection["database"]),
    }
    runner(["pg_dump", "--format=custom", "--file", str(dump_path)], env=environment)
    runner(["pg_restore", "--list", str(dump_path)], env=environment)
    checksum = hashlib.sha256(dump_path.read_bytes()).hexdigest()
    manifest = {
        "dump_file": dump_name, "manifest_file": f"{dump_name}.manifest.json", "sha256": checksum,
        "created_at": timestamp, "git_tag": git_tag, "image_digest": image_digest,
        "alembic_revision": revision,
    }
    (destination_dir / manifest["manifest_file"]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _run(command, **kwargs):
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs)
    return ""


def backup_from_url_file(url_file: Path, destination_dir: Path, git_tag: str, image_digest: str) -> dict:
    """Read a protected URL file and create a checked custom dump."""
    url = make_url(Path(url_file).read_text(encoding="utf-8").strip())
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL database URL is required")
    engine = create_engine(url)
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM app.alembic_version")).scalar_one()
    return create_postgres_backup(
        runner=_run, destination_dir=destination_dir,
        connection={"host": url.host, "port": url.port or 5432, "user": url.username,
                    "password": url.password, "database": url.database},
        revision=revision, git_tag=git_tag, image_digest=image_digest,
    )


if __name__ == "__main__":
    backup_from_url_file(
        Path(os.environ["KICHU_BACKUP_DATABASE_URL_FILE"]),
        Path(os.environ.get("KICHU_BACKUP_DIR", "/backups")),
        os.environ.get("KICHU_GIT_TAG", "unknown"), os.environ.get("KICHU_IMAGE_DIGEST", "unknown"),
    )
