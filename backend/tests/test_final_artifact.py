"""Release image and production-role regressions; only disposable local services."""

import json
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from storage.migrations import upgrade_database
from tests.test_compose_security import _development_config, _production_config

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def final_image():
    tag = f"kichu-review-test:{uuid.uuid4().hex}"
    result = subprocess.run(["docker", "build", "-t", tag, str(ROOT / "backend")],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    try:
        yield tag
    finally:
        subprocess.run(["docker", "image", "rm", tag], capture_output=True)


def _image_run(image, command, **kwargs):
    return subprocess.run(["docker", "run", "--rm", "--network", "none", image, *command],
                          capture_output=True, text=True, encoding="utf-8", **kwargs)


def test_final_image_loads_alembic_revisions(final_image):
    result = _image_run(final_image, ["python", "-c",
        "from storage.migrations import alembic_heads; assert len(alembic_heads()) == 1"])
    assert result.returncode == 0, result.stderr


def test_final_image_imports_radar_api_service(final_image):
    result = _image_run(final_image, ["python", "-c",
        "from services.radar_service import RadarService; "
        "assert RadarService(None).decorate([{'bvid': 'BVfixture'}], 1800000000)[0]['radar']['algorithm_version'] == 'radar-v2'"])
    assert result.returncode == 0, result.stderr


def test_final_image_uses_postgresql_16_client(final_image):
    """A newer dump client can emit SQL that PostgreSQL 16 rejects on restore."""
    result = _image_run(final_image, ["pg_dump", "--version"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("pg_dump (PostgreSQL) 16."), result.stdout


def test_compose_maintenance_cli_works_from_final_image(final_image, tmp_path, monkeypatch):
    monkeypatch.setenv("COMPOSE_PROFILES", "maintenance")
    for config in (_production_config(tmp_path), _development_config()):
        command = config["services"]["migrate"]["command"]
        command[0] = "python"
        result = _image_run(final_image, [*command, "--help"])
        assert result.returncode == 0, result.stderr
    for module in ("scripts.import_sqlite_snapshot", "scripts.run_backfill"):
        result = _image_run(final_image, ["python", "-m", module, "--help"])
        assert result.returncode == 0, result.stderr


def test_api_has_only_allowlisted_proxy_egress(tmp_path):
    for config in (_production_config(tmp_path), _development_config()):
        services = config["services"]
        assert set(services["api"]["networks"]) == {"core"}
        assert services["api"]["environment"]["HTTPS_PROXY"] == "http://api-egress:8080"
        assert services["api"]["environment"]["HTTP_PROXY"] == "http://api-egress:8080"
        assert set(services["api-egress"]["networks"]) == {"core", "egress"}
        assert not services["api-egress"].get("ports")
        assert not services["api-egress"].get("secrets")
        assert "egress" in services["worker"]["networks"]


@pytest.fixture
def bootstrap_roles(empty_postgres_url):
    """Apply only the production role bootstrap SQL in an isolated database."""
    engine = create_engine(empty_postgres_url, isolation_level="AUTOCOMMIT")
    script = (ROOT / "ops/postgres/init-roles.sh").read_text(encoding="utf-8")
    sql = script.split("<<'SQL'", 1)[1].rsplit("SQL", 1)[0]
    sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("\\getenv"))
    for role in ("api", "worker", "migration", "backup"):
        sql = sql.replace(f":'{role}_password'", "'fixture-password'")
    sql = sql.replace("ON DATABASE kichu", f'ON DATABASE "{engine.url.database}"')
    with engine.connect() as connection:
        for role in ("api", "worker", "migration", "backup"):
            # Previous parametrized fixture database has already been dropped.
            connection.exec_driver_sql(f"DROP ROLE IF EXISTS kichu_{role}")
        connection.exec_driver_sql(sql)
    try:
        yield engine
    finally:
        # Database fixture owns cleanup; roles are cluster-scoped and disappear
        # with the --rm PostgreSQL fixture container.
        engine.dispose()


@pytest.fixture
def production_roles(bootstrap_roles):
    """Upgrade a role-bootstrapped database through the migration role."""
    migration_url = bootstrap_roles.url.set(username="kichu_migration", password="fixture-password")
    upgrade_database(migration_url.render_as_string(hide_password=False))
    return bootstrap_roles


def test_bootstrap_roles_leave_schema_ddl_to_the_migration_role(bootstrap_roles):
    before = set(inspect(bootstrap_roles).get_schema_names())
    assert "app" not in before
    assert "auth" not in before

    migration_url = bootstrap_roles.url.set(username="kichu_migration", password="fixture-password")
    upgrade_database(migration_url.render_as_string(hide_password=False))

    assert {"app", "auth"} <= set(inspect(bootstrap_roles).get_schema_names())


@pytest.mark.parametrize("role", ["api", "worker", "backup", "migration"])
def test_production_roles_sequences_and_ddl(production_roles, role):
    engine = production_roles
    with engine.connect() as connection:
        connection.exec_driver_sql(f"SET ROLE kichu_{role}")
        if role in {"worker", "migration"}:
            assert connection.execute(text("INSERT INTO app.crawl_runs(started_at,status) VALUES(1,'running') RETURNING id")).scalar_one() > 0
        else:
            with pytest.raises(Exception, match="permission denied"):
                connection.execute(text("INSERT INTO app.crawl_runs(started_at,status) VALUES(1,'running')"))
        if role in {"api", "migration"}:
            assert connection.execute(text("INSERT INTO auth.collector_credential_handoffs(action,requested_by,requested_at) VALUES('delete','fixture',1) RETURNING id")).scalar_one() > 0
        elif role == "worker":
            connection.execute(text("SELECT id FROM auth.collector_credential_handoffs LIMIT 1"))
            with pytest.raises(Exception, match="permission denied"):
                connection.execute(text("INSERT INTO auth.collector_credential_handoffs(action,requested_by,requested_at) VALUES('delete','fixture',1)"))
        if role == "backup":
            connection.exec_driver_sql("SELECT last_value FROM app.crawl_runs_id_seq")
            with pytest.raises(Exception, match="permission denied"):
                connection.exec_driver_sql("INSERT INTO app.crawl_runs(started_at,status) VALUES(1,'running')")
            with pytest.raises(Exception, match="permission denied"):
                connection.exec_driver_sql("SELECT nextval('app.crawl_runs_id_seq')")
        for schema in ("app", "auth", "public"):
            statement = f"CREATE TABLE {schema}.role_probe_{role}(id int)"
            if role == "migration" and schema != "public":
                connection.exec_driver_sql(statement)
                connection.exec_driver_sql(f"DROP TABLE {schema}.role_probe_{role}")
            else:
                with pytest.raises(Exception, match="permission denied"):
                    connection.exec_driver_sql(statement)


def test_api_can_write_state_but_worker_cannot_read_browser_sessions(production_roles):
    with production_roles.connect() as connection:
        connection.exec_driver_sql("SET ROLE kichu_api")
        connection.execute(text("""
            INSERT INTO app.dashboard_state(name,payload,version,updated_at)
            VALUES('current','{}',0,1)
        """))
    with production_roles.connect() as connection:
        connection.exec_driver_sql("SET ROLE kichu_worker")
        with pytest.raises(Exception, match="permission denied"):
            connection.execute(text("SELECT token FROM auth.browser_sessions"))
