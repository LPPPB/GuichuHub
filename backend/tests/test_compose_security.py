import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
LEGACY_RUNTIME_ENV = {
    "KICHU_DB_PATH", "KICHU_AUTH_DB_PATH", "KICHU_STATE_PATH", "KICHU_BACKUP_DIR",
}


def _production_config(tmp_path, *, profiles=None):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "write_token").write_text("write-token", encoding="utf-8")
    for name in (
        "postgres_superuser_password", "postgres_api_password", "postgres_worker_password",
        "postgres_migration_password", "postgres_backup_password", "api_database_url",
        "worker_database_url", "migration_database_url", "backup_database_url",
    ):
        (secrets_dir / name).write_text("postgresql+psycopg://user:password@postgres/kichu", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "KICHU_HOST_SECRETS_DIR": str(secrets_dir),
            "KICHU_HOST_WRITE_TOKEN_FILE": str(secrets_dir / "write_token"),
            "KICHU_HOST_POSTGRES_DIR": str(tmp_path / "postgres-data"),
            "KICHU_HOST_POSTGRES_SUPERUSER_PASSWORD_FILE": str(secrets_dir / "postgres_superuser_password"),
            "KICHU_HOST_POSTGRES_API_PASSWORD_FILE": str(secrets_dir / "postgres_api_password"),
            "KICHU_HOST_POSTGRES_WORKER_PASSWORD_FILE": str(secrets_dir / "postgres_worker_password"),
            "KICHU_HOST_POSTGRES_MIGRATION_PASSWORD_FILE": str(secrets_dir / "postgres_migration_password"),
            "KICHU_HOST_POSTGRES_BACKUP_PASSWORD_FILE": str(secrets_dir / "postgres_backup_password"),
            "KICHU_HOST_API_DATABASE_URL_FILE": str(secrets_dir / "api_database_url"),
            "KICHU_HOST_WORKER_DATABASE_URL_FILE": str(secrets_dir / "worker_database_url"),
            "KICHU_HOST_MIGRATION_DATABASE_URL_FILE": str(secrets_dir / "migration_database_url"),
            "KICHU_HOST_BACKUP_DATABASE_URL_FILE": str(secrets_dir / "backup_database_url"),
            "KICHU_GIT_TAG": "v3-test",
            "KICHU_IMAGE_DIGEST": "sha256:test",
        }
    )
    if profiles is not None:
        env["COMPOSE_PROFILES"] = profiles
    result = subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "compose.prod.yml"), "config", "--format", "json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _development_config():
    result = subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "compose.dev.yml"), "config", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_production_services_receive_only_role_specific_database_url_secrets(tmp_path):
    config = _production_config(tmp_path)
    api = config["services"]["api"]
    worker = config["services"]["worker"]
    assert api["environment"]["KICHU_API_DATABASE_URL_FILE"] == "/run/secrets/api_database_url"
    assert worker["environment"]["KICHU_WORKER_DATABASE_URL_FILE"] == "/run/secrets/worker_database_url"
    for service in (api, worker):
        assert all(volume["target"] not in {"/data/db", "/data/auth", "/data/state"} for volume in service["volumes"])
        assert LEGACY_RUNTIME_ENV.isdisjoint(service["environment"])


def test_development_services_have_no_legacy_runtime_persistence_environment():
    config = _development_config()
    for name in ("api", "worker"):
        assert LEGACY_RUNTIME_ENV.isdisjoint(config["services"][name]["environment"])


def test_write_token_secret_is_available_only_to_api(tmp_path):
    config = _production_config(tmp_path)
    api = config["services"]["api"]
    worker = config["services"]["worker"]

    assert api["environment"]["KICHU_WRITE_TOKEN_FILE"] == "/run/secrets/write_token"
    assert "KICHU_WRITE_TOKEN" not in api["environment"]
    assert "KICHU_WRITE_TOKEN" not in worker["environment"]
    assert "KICHU_WRITE_TOKEN_FILE" not in worker["environment"]
    assert {secret["target"] for secret in api["secrets"]} >= {"/run/secrets/write_token"}
    assert "secrets" not in worker or all(
        secret["target"] != "/run/secrets/write_token" for secret in worker["secrets"]
    )


def test_api_has_read_only_cookie_mount_and_worker_owns_writes(tmp_path):
    config = _production_config(tmp_path)
    api = config["services"]["api"]
    worker = config["services"]["worker"]
    api_private = next(v for v in config["services"]["api"]["volumes"] if v["target"] == "/data/private")
    worker_private = next(v for v in config["services"]["worker"]["volumes"] if v["target"] == "/data/private")

    assert api_private["read_only"] is True
    assert worker_private.get("read_only", False) is False
    assert all(volume["target"] != "/data/auth" for volume in config["services"]["worker"]["volumes"])
    assert api["environment"]["KICHU_COOKIE_WRITES_ENABLED"] == "0"
    assert worker["environment"]["KICHU_COOKIE_WRITES_ENABLED"] == "1"


def test_backup_requires_explicit_release_identity(tmp_path):
    config = _production_config(tmp_path, profiles="maintenance")
    backup = config["services"]["backup"]
    assert backup["environment"]["KICHU_GIT_TAG"] == "v3-test"
    assert backup["environment"]["KICHU_IMAGE_DIGEST"] == "sha256:test"


def test_ci_compose_validation_supplies_non_production_release_identity():
    workflow = (ROOT / ".github" / "workflows" / "backend.yml").read_text(encoding="utf-8")
    compose_step = workflow.split("- name: Validate Compose files", 1)[1]

    assert "export KICHU_GIT_TAG=ci-test" in compose_step
    assert "export KICHU_IMAGE_DIGEST=sha256:ci-test" in compose_step
