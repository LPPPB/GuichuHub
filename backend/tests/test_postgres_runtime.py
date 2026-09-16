"""Process startup must configure PostgreSQL adapters without DDL."""

from storage import auth_store, database, db, tracked_ups


def test_api_runtime_installs_postgres_adapters_from_its_url_file(tmp_path):
    """A production API process has one file-backed PostgreSQL boundary."""
    url_file = tmp_path / "api-url"
    url_file.write_text("postgresql+psycopg://api:secret@db/kichu\n", encoding="utf-8")

    from storage.runtime import configure_postgres_runtime

    try:
        resources = configure_postgres_runtime(
            "api", {"KICHU_API_DATABASE_URL_FILE": str(url_file)}
        )

        assert resources.role == "api"
        assert db.get_business_repository() is resources.business
        assert auth_store._auth_repository is resources.auth
        assert database._state_repository is resources.state
        assert tracked_ups._state_repository is resources.state
    finally:
        db.configure_business_repository(None)
        auth_store.configure_auth_repository(None)
        database.configure_state_repository(None)
        tracked_ups.configure_state_repository(None)
