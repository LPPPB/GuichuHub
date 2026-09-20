"""Strict, file-backed PostgreSQL connection settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from sqlalchemy.engine import URL, make_url


class ConfigurationError(ValueError):
    """Raised when a process has no safe PostgreSQL configuration."""


_URL_FILE_BY_ROLE = {
    "api": "KICHU_API_DATABASE_URL_FILE",
    "worker": "KICHU_WORKER_DATABASE_URL_FILE",
    "migration": "KICHU_MIGRATION_DATABASE_URL_FILE",
    "offline": "KICHU_DATABASE_URL_FILE",
}


@dataclass(frozen=True)
class DatabaseSettings:
    url: URL
    source_file: Path

    @classmethod
    def from_environment(cls, env: Mapping[str, str], role: str) -> "DatabaseSettings":
        try:
            variable = _URL_FILE_BY_ROLE[role]
        except KeyError as error:
            raise ConfigurationError(f"unknown database role: {role}") from error
        raw_path = str(env.get(variable, "")).strip()
        if not raw_path:
            raise ConfigurationError(f"{variable} must name a protected URL file")
        path = Path(raw_path).expanduser()
        try:
            raw_url = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ConfigurationError(f"cannot read database URL file for role {role}") from error
        if not raw_url:
            raise ConfigurationError(f"database URL file for role {role} is empty")
        try:
            url = make_url(raw_url)
        except Exception as error:
            raise ConfigurationError("database URL is invalid") from error
        if url.get_backend_name() != "postgresql":
            raise ConfigurationError("PostgreSQL database URL is required")
        return cls(url=url, source_file=path)
