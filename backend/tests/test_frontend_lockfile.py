import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def test_frontend_lockfile_supports_clean_node_22_install():
    package_json = FRONTEND / "package.json"
    package_lock = FRONTEND / "package-lock.json"
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--mount",
            f"type=bind,src={package_json},dst=/workspace/package.json,readonly",
            "--mount",
            f"type=bind,src={package_lock},dst=/workspace/package-lock.json,readonly",
            "node:22-alpine",
            "sh",
            "-lc",
            "cd /workspace && npm ci --ignore-scripts --dry-run --no-audit --no-fund",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )

    assert result.returncode == 0, result.stderr


def test_frontend_builder_uses_node_22_for_the_locked_toolchain():
    dockerfile = (FRONTEND / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM node:22-alpine AS builder" in dockerfile
