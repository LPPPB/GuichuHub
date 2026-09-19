"""Operational PostgreSQL Compose and backup contracts."""

import json
import hashlib
from pathlib import Path

import pytest


def test_production_postgres_has_no_host_port_and_core_only(tmp_path):
    from tests.test_compose_security import _production_config
    compose = Path(__file__).resolve().parents[2].joinpath("compose.prod.yml").read_text(encoding="utf-8")

    assert "  postgres:" in compose
    assert "postgres:16" in compose
    assert "KICHU_HOST_POSTGRES_DIR" in compose
    assert "  core:\n    internal: true" in compose
    postgres_block = compose.split("  postgres:", 1)[1].split("\n  migrate:", 1)[0]
    assert "ports:" not in postgres_block
    services = _production_config(tmp_path)["services"]
    assert set(services["api"]["networks"]) == {"core"}
    assert "egress" in services["worker"]["networks"]


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


@pytest.mark.parametrize(("git_tag", "image_digest"), [("unknown", "sha256:test"), ("v3-test", "unknown"), ("", "sha256:test")])
def test_custom_postgres_backup_requires_release_identity(tmp_path, git_tag, image_digest):
    """Missing release identity must not create a restorable-looking backup."""
    from ops.backup.backup_postgres import create_postgres_backup

    def runner(*_args, **_kwargs):
        pytest.fail("backup command must not run without release identity")

    with pytest.raises(ValueError, match="release identity"):
        create_postgres_backup(
            runner=runner,
            destination_dir=tmp_path,
            connection={"host": "db", "user": "backup", "password": "secret", "database": "kichu"},
            revision="0002_recovery_and_identity", git_tag=git_tag, image_digest=image_digest,
        )
    assert list(tmp_path.iterdir()) == []


def test_restore_drill_rejects_tampered_dump_before_creating_database(tmp_path, monkeypatch):
    """A corrupted dump cannot cause an operator action against PostgreSQL."""
    from ops.backup.restore_drill import restore_drill

    dump = tmp_path / "fixture.dump"
    dump.write_bytes(b"altered payload")
    manifest = tmp_path / "fixture.dump.manifest.json"
    manifest.write_text(json.dumps({
        "sha256": hashlib.sha256(b"original payload").hexdigest(),
        "alembic_revision": "0002_recovery_and_identity",
    }), encoding="utf-8")
    migration_url = tmp_path / "migration-url"
    provisioner_url = tmp_path / "provisioner-url"
    migration_url.write_text("postgresql+psycopg://migration:secret@db/kichu", encoding="utf-8")
    provisioner_url.write_text("postgresql+psycopg://provisioner:secret@db/postgres", encoding="utf-8")
    commands = []
    monkeypatch.setattr("ops.backup.restore_drill.subprocess.run", lambda command, **_kwargs: commands.append(command))

    with pytest.raises(ValueError, match="checksum"):
        restore_drill(
            migration_url, dump, "kichu_restore_drill_fixture",
            provisioner_database_url_file=provisioner_url, manifest_file=manifest,
        )
    assert commands == []
