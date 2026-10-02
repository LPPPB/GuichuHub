"""Additive job schema and actual PostgreSQL privilege boundaries."""
import uuid

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from storage.migrations import _config, alembic_heads, upgrade_database


def test_analysis_job_is_the_only_new_head():
    assert alembic_heads() == ["0003_up_analysis_jobs"]


def test_upgrade_from_0002_preserves_observations(empty_postgres_url):
    command.upgrade(_config(empty_postgres_url), "0002_recovery_and_identity")
    engine = create_engine(empty_postgres_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO app.ups(mid,name) VALUES(1,'kept')"))
        connection.execute(text("INSERT INTO app.up_observations(mid,ts,payload) VALUES(1,123,CAST(:payload AS jsonb))"), {"payload": '{"views":9}'})
    upgrade_database(empty_postgres_url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT payload FROM app.up_observations WHERE mid=1 AND ts=123")).scalar_one() == {"views": 9}
        assert connection.execute(text("SELECT to_regclass('app.up_analysis_jobs')")).scalar_one() is not None
    engine.dispose()


def test_job_permissions_do_not_expand_api_collection_writes(empty_postgres_url):
    engine = create_engine(empty_postgres_url, isolation_level="AUTOCOMMIT")
    # Roles live only in this disposable test cluster, never the deployed server.
    with engine.connect() as connection:
        for name in ("kichu_api", "kichu_worker", "kichu_backup"):
            connection.execute(text(f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{name}') THEN CREATE ROLE {name}; END IF; END $$"))
    upgrade_database(empty_postgres_url)
    with engine.connect() as connection:
        privileges = {p: connection.execute(text("SELECT has_table_privilege('kichu_api','app.up_analysis_jobs',:p)"), {"p": p}).scalar_one() for p in ("SELECT", "INSERT", "UPDATE", "DELETE")}
        assert privileges == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False}
        assert connection.execute(text("SELECT has_table_privilege('kichu_worker','app.up_analysis_jobs','UPDATE')")).scalar_one()
        assert connection.execute(text("SELECT has_table_privilege('kichu_backup','app.up_analysis_jobs','SELECT')")).scalar_one()
        for table in ("video_snapshot_documents", "calendar_videos", "videos"):
            assert not connection.execute(text(f"SELECT has_table_privilege('kichu_api','app.{table}','INSERT')")).scalar_one()
        connection.execute(text("SET ROLE kichu_api"))
        connection.execute(text("INSERT INTO app.up_analysis_jobs(id,status,roster,created_at,updated_at,requested_by) VALUES(:id,'queued','[]',1,1,'test')"), {"id": str(uuid.uuid4())})
        with pytest.raises(Exception, match="permission denied"):
            connection.execute(text("UPDATE app.up_analysis_jobs SET status='running'"))
        connection.execute(text("RESET ROLE"))
        # Release privileges before later tests bootstrap the same role names.
        for name in ("kichu_api", "kichu_worker", "kichu_backup"):
            connection.execute(text(f"DROP OWNED BY {name}"))
            connection.execute(text(f"DROP ROLE {name}"))
    engine.dispose()


def test_only_one_active_analysis_job_allowed(clean_postgres_data):
    engine = create_engine(clean_postgres_data)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO app.up_analysis_jobs(id,status,roster,created_at,updated_at,requested_by) VALUES(:id,'queued','[]',1,1,'test')"), {"id": str(uuid.uuid4())})
    with pytest.raises(Exception, match="duplicate key"):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO app.up_analysis_jobs(id,status,roster,created_at,updated_at,requested_by) VALUES(:id,'finalizing','[]',2,2,'test')"), {"id": str(uuid.uuid4())})
    engine.dispose()
