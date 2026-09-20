"""PostgreSQL baseline replacing V3 SQLite schema versions 1 through 11."""

from alembic import op

from pathlib import Path

revision = "0001_postgresql_v3_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")
    op.execute(Path(__file__).with_name("0001_baseline.sql").read_text(encoding="utf-8"))
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kichu_api') THEN
            GRANT USAGE ON SCHEMA app, auth TO kichu_api;
            GRANT SELECT ON ALL TABLES IN SCHEMA app TO kichu_api;
            GRANT INSERT, UPDATE, DELETE ON TABLE
                app.dashboard_state, app.favorites, app.tracked_ups,
                app.tracked_up_settings, app.tracking_requests, app.calendar_backfill_jobs,
                app.calendar_backfill_job_items, app.ups, app.up_observations
            TO kichu_api;
            GRANT USAGE, SELECT ON SEQUENCE auth.collector_credential_handoffs_id_seq TO kichu_api;
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
                auth.admin_accounts, auth.browser_sessions, auth.collector_credential_handoffs
            TO kichu_api;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kichu_worker') THEN
            GRANT USAGE ON SCHEMA app, auth TO kichu_worker;
            GRANT SELECT ON ALL TABLES IN SCHEMA app TO kichu_worker;
            GRANT INSERT, UPDATE, DELETE ON TABLE
                app.videos, app.ups, app.video_observations, app.video_tags,
                app.word_observations, app.crawl_runs, app.up_observations,
                app.up_staff_memberships, app.video_snapshot_documents,
                app.calendar_videos, app.calendar_video_authors,
                app.calendar_backfill_jobs, app.calendar_backfill_job_items,
                app.dashboard_state, app.tracked_ups, app.tracked_up_settings,
                app.up_card_cache, app.backfill_progress, app.worker_heartbeats
            TO kichu_worker;
            GRANT USAGE, SELECT ON SEQUENCE app.crawl_runs_id_seq TO kichu_worker;
            GRANT SELECT, DELETE ON TABLE auth.collector_credential_handoffs TO kichu_worker;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kichu_backup') THEN
            GRANT USAGE ON SCHEMA app, auth TO kichu_backup;
            GRANT SELECT ON ALL TABLES IN SCHEMA app, auth TO kichu_backup;
            GRANT SELECT ON ALL SEQUENCES IN SCHEMA app, auth TO kichu_backup;
        END IF;
    END $$;
    """)


def downgrade():
    op.execute("DROP SCHEMA auth CASCADE")
    op.execute("DROP SCHEMA app CASCADE")
