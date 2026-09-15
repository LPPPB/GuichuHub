import pytest

from storage.settings import ConfigurationError, DatabaseSettings


def test_api_role_reads_postgresql_url_only_from_file(tmp_path):
    """Removing file-only secret loading must fail this API configuration contract."""
    url_file = tmp_path / "api-url"
    url_file.write_text("postgresql+psycopg://api:secret@db/kichu\n", encoding="utf-8")

    settings = DatabaseSettings.from_environment(
        {"KICHU_API_DATABASE_URL_FILE": str(url_file)}, role="api"
    )

    assert settings.url.render_as_string(hide_password=True).startswith(
        "postgresql+psycopg://api:***"
    )


def test_sqlite_url_is_rejected_before_connecting(tmp_path):
    """Changing the dialect guard to permit SQLite must fail this production boundary."""
    url_file = tmp_path / "url"
    url_file.write_text("sqlite:///forbidden.db", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="PostgreSQL"):
        DatabaseSettings.from_environment(
            {"KICHU_API_DATABASE_URL_FILE": str(url_file)}, role="api"
        )
