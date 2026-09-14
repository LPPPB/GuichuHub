import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def _production_config(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "write_token").write_text("write-token", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "KICHU_HOST_SECRETS_DIR": str(secrets_dir),
            "KICHU_HOST_WRITE_TOKEN_FILE": str(secrets_dir / "write_token"),
        }
    )
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


def test_production_services_share_explicit_current_state_path(tmp_path):
    config = _production_config(tmp_path)
    for service_name in ("api", "worker"):
        service = config["services"][service_name]
        assert service["environment"]["KICHU_STATE_PATH"] == "/data/state/inspiration_db.json"
        assert any(volume["target"] == "/data/state" for volume in service["volumes"])


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
    assert any(volume["target"] == "/data/auth" for volume in config["services"]["worker"]["volumes"])
    assert api["environment"]["KICHU_COOKIE_WRITES_ENABLED"] == "0"
    assert worker["environment"]["KICHU_COOKIE_WRITES_ENABLED"] == "1"
