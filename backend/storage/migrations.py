"""Programmatic Alembic operations used only by maintenance tooling and tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


_BACKEND = Path(__file__).resolve().parents[1]


def _config(url: str | None = None) -> Config:
    config = Config(str(_BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND / "alembic"))
    if url is not None:
        config.set_main_option("sqlalchemy.url", url)
    return config


def alembic_heads() -> list[str]:
    return list(ScriptDirectory.from_config(_config()).get_heads())


def upgrade_database(url: str) -> None:
    command.upgrade(_config(url), "head")
