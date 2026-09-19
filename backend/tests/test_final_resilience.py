"""Failure recovery, credential safety and migration-history regressions."""

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from alembic import command
from sqlalchemy import Column, Integer, Table, create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from storage.migrations import _config, upgrade_database
from storage.models import Base, backfill_progress
from storage.repositories.state import StateRepository


@pytest.mark.parametrize("factory", ["runtime", "auth", "state", "business"])
def test_database_exception_tracebacks_never_contain_cookie_or_session_data(postgres_url, clean_postgres_data, caplog, factory):
    from storage.postgres import create_session_factory
    from storage.settings import DatabaseSettings
    from storage.repositories.auth import AuthRepository
    from storage.repositories.business import BusinessRepository
    if factory == "runtime":
        sessions = create_session_factory(DatabaseSettings(make_url(postgres_url), Path("fixture")))
    else:
        sessions = {"auth": AuthRepository, "state": StateRepository, "business": BusinessRepository}[factory].from_url(postgres_url)._sessions
    with caplog.at_level(logging.ERROR):
        try:
            with sessions.begin() as session:
                session.execute(text("INSERT INTO auth.collector_credential_handoffs(action,payload,requested_by,requested_at) VALUES(:action,CAST(:payload AS jsonb),:owner,1)"),
                    {"action": "invalid", "payload": '{"SESSDATA":"COOKIE_MARKER_456"}', "owner": "SESSION_MARKER_789"})
        except Exception:
            logging.getLogger("fixture").exception("Database action failed")
        else:
            pytest.fail("CHECK violation must exercise the exception path")
    assert "COOKIE_MARKER_456" not in caplog.text
    assert "SESSION_MARKER_789" not in caplog.text
    assert "SESSDATA" not in caplog.text


def test_encoded_database_password_survives_alembic_and_errors_are_redacted(empty_postgres_url, caplog):
    url = make_url(empty_postgres_url).set(username="encoded_fixture", password="fixture@:%password")
    with create_engine(empty_postgres_url, isolation_level="AUTOCOMMIT").connect() as connection:
        connection.execute(text("CREATE ROLE encoded_fixture LOGIN PASSWORD 'fixture@:%password'"))
        connection.exec_driver_sql(f'GRANT CREATE ON DATABASE "{url.database}" TO encoded_fixture')
    upgrade_database(url.render_as_string(hide_password=False))
    with create_engine(url).connect() as connection:
        assert connection.execute(text("SELECT version_num FROM app.alembic_version")).scalar_one()
    unreachable_url = "postgresql+psycopg://user:URL_SECRET_MARKER%40@127.0.0.1:1/db?connect_timeout=1"
    with caplog.at_level(logging.ERROR):
        try:
            upgrade_database(unreachable_url)
        except Exception:
            logging.getLogger("fixture").exception("Migration failed")
    assert "URL_SECRET_MARKER" not in caplog.text


def test_heartbeat_recovers_after_transient_failure():
    from storage.health import HeartbeatService
    stopped, recovered = Event(), Event()
    attempts = []
    def repository(worker, now, details):
        attempts.append(now)
        if len(attempts) == 1:
            raise ConnectionError("transient fixture")
        recovered.set()
        stopped.set()
    thread = HeartbeatService(repository, "fixture", {}, interval_seconds=0.01).start(stopped)
    try:
        assert recovered.wait(1), "one failed beat permanently stopped the heartbeat"
    finally:
        stopped.set()
        thread.join(timeout=1)
    assert len(attempts) == 2


def test_baseline_is_frozen_against_future_models(empty_postgres_url):
    future = Table("future_model_probe", Base.metadata, Column("id", Integer, primary_key=True), schema="app")
    try:
        command.upgrade(_config(empty_postgres_url), "0001_postgresql_v3_baseline")
        assert "future_model_probe" not in inspect(create_engine(empty_postgres_url)).get_table_names(schema="app")
    finally:
        Base.metadata.remove(future)


def test_fresh_and_incremental_upgrades_have_identical_schema(empty_postgres_url, postgres_url):
    command.upgrade(_config(empty_postgres_url), "0001_postgresql_v3_baseline")
    upgrade_database(empty_postgres_url)
    def shape(url):
        inspector = inspect(create_engine(url))
        return {f"{schema}.{table}": {
            "columns": [(col["name"], str(col["type"]), col["nullable"], col.get("default")) for col in inspector.get_columns(table, schema)],
            "pk": inspector.get_pk_constraint(table, schema),
            "indexes": inspector.get_indexes(table, schema),
            "unique": inspector.get_unique_constraints(table, schema),
        } for schema in ("app", "auth") for table in inspector.get_table_names(schema)}
    assert shape(empty_postgres_url) == shape(postgres_url)


def test_calendar_baseline_upgrade_keeps_best_metrics_when_best_mid_is_higher(empty_postgres_url):
    command.upgrade(_config(empty_postgres_url), "0001_postgresql_v3_baseline")
    engine = create_engine(empty_postgres_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO app.ups(mid, name, face, tracked) VALUES
                    (100, 'lower-author', '', true),
                    (200, 'best-author', '', true);
                INSERT INTO app.videos(bvid, mid, first_seen, source, observe_tier)
                    VALUES ('BVcalendar-dupe', 100, 1, 'fixture', 'hot');
                INSERT INTO app.calendar_videos(
                    bvid, mid, pub_date, pub_date_str, views, title, fetched_at,
                    last_seen_at, missing_count, status
                ) VALUES
                    ('BVcalendar-dupe', 100, 1, '1970-01-01', 1, 'lower', 1, 1, 0, 'active'),
                    ('BVcalendar-dupe', 200, 1, '1970-01-01', 999, 'best', 2, 2, 0, 'active');
            """))
        command.upgrade(_config(empty_postgres_url), "head")
        with engine.connect() as connection:
            row = connection.execute(text("""
                SELECT mid, views, title FROM app.calendar_videos
                WHERE bvid = 'BVcalendar-dupe'
            """)).mappings().one()
            authors = connection.execute(text("""
                SELECT mid FROM app.calendar_video_authors
                WHERE bvid = 'BVcalendar-dupe' ORDER BY mid
            """)).scalars().all()
        assert row["mid"] == 100
        assert row["views"] == 999
        assert row["title"] == "best"
        assert authors == [100, 200]
    finally:
        engine.dispose()


@pytest.mark.parametrize("terminal", ["withdrawn", "rejected", "approved"])
def test_repeated_tracking_request_lifecycles_preserve_history(postgres_url, clean_postgres_data, terminal):
    repository = StateRepository.from_url(postgres_url)
    for index in range(3):
        now = 100 + index * 86400
        request_id = repository.create_tracking_request(8, "visitor", {}, "fixture", now)
        if terminal == "withdrawn":
            assert repository.withdraw_tracking_request(request_id, "visitor", now + 1) is None
        else:
            repository.review_tracking_request(request_id, "reject" if terminal == "rejected" else "approve", now + 1)
            if terminal == "approved":
                removal = repository.create_tracking_request(8, "visitor", {}, "remove", now + 2, request_type="remove")
                repository.review_tracking_request(removal, "approve", now + 3)
    history = repository.tracking_requests_for("visitor")
    assert len(history) == (6 if terminal == "approved" else 3)


def test_backfill_claim_excludes_live_competitor_and_recovers_after_exception(postgres_url, clean_postgres_data):
    from scripts.run_backfill import run_resumable_backfill
    sessions = StateRepository.from_url(postgres_url)._sessions
    entered, release = Event(), Event()
    seen = []
    def slow(cursor):
        seen.append(cursor)
        entered.set()
        assert release.wait(3)
        return {"offset": 10}, True
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run_resumable_backfill, sessions, "concurrent", slow)
        try:
            assert entered.wait(2)
            assert run_resumable_backfill(sessions, "concurrent", lambda cursor: ({"offset": 999}, True)) is False
        finally:
            release.set()
        assert first.result()
    with sessions() as session:
        assert session.execute(select(backfill_progress.c.cursor).where(backfill_progress.c.name == "concurrent")).scalar_one() == {"offset": 10}
    with pytest.raises(RuntimeError, match="interrupted"):
        run_resumable_backfill(sessions, "retry", lambda cursor: (_ for _ in ()).throw(RuntimeError("interrupted")))
    assert run_resumable_backfill(sessions, "retry", lambda cursor: ({"resumed": True}, True))


def test_backfill_expired_claim_is_recoverable_and_fences_stale_checkpoint(postgres_url, clean_postgres_data):
    from scripts.run_backfill import run_resumable_backfill
    sessions = StateRepository.from_url(postgres_url)._sessions
    entered, release = Event(), Event()
    now = [100]
    def stale(cursor):
        entered.set()
        assert release.wait(3)
        return {"offset": 1}, True
    with ThreadPoolExecutor() as executor:
        first = executor.submit(run_resumable_backfill, sessions, "expired", stale, now=lambda: now[0], lease_seconds=10)
        try:
            assert entered.wait(2)
            now[0] = 111
            assert run_resumable_backfill(sessions, "expired", lambda cursor: ({"offset": 20}, True), now=lambda: now[0], lease_seconds=10)
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="claim"):
            first.result()
    with sessions() as session:
        assert session.execute(select(backfill_progress.c.cursor).where(backfill_progress.c.name == "expired")).scalar_one() == {"offset": 20}
