"""Operational PostgreSQL Compose and backup contracts."""

import json
from pathlib import Path


def test_production_postgres_has_no_host_port_and_core_only():
    compose = Path(__file__).resolve().parents[2].joinpath("compose.prod.yml").read_text(encoding="utf-8")

    assert "  postgres:" in compose
    assert "postgres:16" in compose
    assert "KICHU_HOST_POSTGRES_DIR" in compose
    assert "  core:\n    internal: true" in compose
    postgres_block = compose.split("  postgres:", 1)[1].split("\n  migrate:", 1)[0]
    assert "ports:" not in postgres_block
    api_block = compose.split("  api:", 1)[1].split("\n  worker:", 1)[0]
    worker_block = compose.split("  worker:", 1)[1].split("\n  backup:", 1)[0]
    assert "egress" not in api_block
    assert "egress" in worker_block


def test_custom_postgres_backup_writes_verified_manifest(tmp_path):
    from ops.backup.backup_postgres import create_postgres_backup

    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "pg_dump":
            Path(command[command.index("--file") + 1]).write_bytes(b"custom dump")
        return ""

    manifest = create_postgres_backup(
        runner=runner, destination_dir=tmp_path, connection={"host": "db", "port": "5432", "user": "backup", "password": "secret", "database": "kichu"},
        revision="0001_postgresql_v3_baseline", git_tag="v3-test", image_digest="sha256:test",
    )

    assert manifest["sha256"]
    assert manifest["alembic_revision"] == "0001_postgresql_v3_baseline"
    assert any(command[0] == "pg_restore" and "--list" in command for command, _ in calls)
    assert json.loads((tmp_path / manifest["manifest_file"]).read_text(encoding="utf-8"))["git_tag"] == "v3-test"
