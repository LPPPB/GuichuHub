"""Calendar identity upgrades keep historical reconciliation outside Alembic."""

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from storage.migrations import _config


def _seed_duplicate_calendar_rows(database_url):
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO app.ups(mid, name, face, tracked) VALUES
                    (10, 'first-author', '', true),
                    (20, 'best-author', '', true);
                INSERT INTO app.videos(bvid, mid, first_seen, source, observe_tier)
                    VALUES ('BVidentity', 10, 1, 'fixture', 'hot');
                INSERT INTO app.calendar_videos(
                    bvid, mid, pub_date, pub_date_str, views, title, fetched_at,
                    last_seen_at, missing_count, status
                ) VALUES
                    ('BVidentity', 10, 1, '1970-01-01', 1, 'older', 1, 1, 0, 'active'),
                    ('BVidentity', 20, 1, '1970-01-01', 999, 'best', 2, 2, 0, 'active');
            """))
    finally:
        engine.dispose()


def test_calendar_identity_backfill_is_resumable_before_primary_key_upgrade(empty_postgres_url):
    from scripts.calendar_identity_backfill import run_calendar_identity_backfill

    command.upgrade(_config(empty_postgres_url), "0001_postgresql_v3_baseline")
    _seed_duplicate_calendar_rows(empty_postgres_url)

    assert run_calendar_identity_backfill(empty_postgres_url, batch_size=1, max_steps=1) is False
    assert run_calendar_identity_backfill(empty_postgres_url, batch_size=1, max_steps=1) is True

    engine = create_engine(empty_postgres_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(text("""
                SELECT mid, views, title FROM app.calendar_videos WHERE bvid = 'BVidentity'
            """)).mappings().one()
            authors = connection.execute(text("""
                SELECT mid FROM app.calendar_video_authors WHERE bvid = 'BVidentity' ORDER BY mid
            """)).scalars().all()
        assert dict(row) == {"mid": 10, "views": 999, "title": "best"}
        assert authors == [10, 20]
    finally:
        engine.dispose()

    command.upgrade(_config(empty_postgres_url), "head")


def test_calendar_identity_migration_refuses_unreconciled_history(empty_postgres_url):
    command.upgrade(_config(empty_postgres_url), "0001_postgresql_v3_baseline")
    _seed_duplicate_calendar_rows(empty_postgres_url)

    with pytest.raises(RuntimeError, match="calendar identity backfill"):
        command.upgrade(_config(empty_postgres_url), "head")
