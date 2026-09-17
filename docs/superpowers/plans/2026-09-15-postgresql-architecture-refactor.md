# PostgreSQL Architecture Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace V3 runtime SQLite and mutable JSON persistence with one PostgreSQL 16 database using `app` and `auth` schemas.

**Architecture:** SQLAlchemy models and repositories are the sole persistence boundary, while Alembic owns all DDL. Existing storage functions remain API-compatible adapters while process-specific URL-file settings, a Worker heartbeat, offline import, and privileged maintenance commands create clear runtime and operational boundaries.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy 2.x, Alembic, psycopg 3, PostgreSQL 16, Docker Compose, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-postgresql-architecture-refactor-design.md`

## Global Constraints

- Production persistence uses PostgreSQL only; SQLite and JSON are explicit offline import inputs only.
- API and Worker never execute DDL, Alembic, `create_all`, SQLite persistence, or runtime JSON persistence.
- URLs come only from `*_DATABASE_URL_FILE`; non-PostgreSQL URLs fail before a connection is created and secrets are never logged.
- Alembic has exactly one head and baseline revision `0001_postgresql_v3_baseline`.
- All behavior changes start with a test that fails for the named missing behavior, then receive the smallest implementation and focused verification.
- No command targets a production host/database, imports real snapshots, deletes backups, or deploys.

---

### Task 1: Settings, engine lifecycle, and dependency floor

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock`
- Create: `backend/storage/settings.py`, `backend/storage/postgres.py`, `backend/tests/test_postgres_settings.py`

**Interfaces:**
- Produces `DatabaseSettings.from_environment(env, role) -> DatabaseSettings` and `create_session_factory(settings) -> sessionmaker`.

- [x] **Step 1: Write the failing settings tests**

```python
def test_api_role_reads_postgresql_url_only_from_file(tmp_path):
    path = tmp_path / "api-url"
    path.write_text("postgresql+psycopg://api:secret@db/kichu\n")
    settings = DatabaseSettings.from_environment({"KICHU_API_DATABASE_URL_FILE": str(path)}, "api")
    assert settings.url.render_as_string(hide_password=True).startswith("postgresql+psycopg://api:***")

def test_sqlite_url_is_rejected_before_connecting(tmp_path):
    path = tmp_path / "url"
    path.write_text("sqlite:///forbidden.db")
    with pytest.raises(ConfigurationError, match="PostgreSQL"):
        DatabaseSettings.from_environment({"KICHU_API_DATABASE_URL_FILE": str(path)}, "api")
```

- [x] **Step 2: Run the focused test and observe missing-module failure**

Run: `uv run pytest tests/test_postgres_settings.py -q --no-cov`

- [x] **Step 3: Add pinned SQLAlchemy/Alembic/psycopg dependencies and minimal file-only configuration**

```python
URL_FILE_BY_ROLE = {"api": "KICHU_API_DATABASE_URL_FILE", "worker": "KICHU_WORKER_DATABASE_URL_FILE", "migration": "KICHU_MIGRATION_DATABASE_URL_FILE"}
if make_url(raw_url).get_backend_name() != "postgresql":
    raise ConfigurationError("PostgreSQL database URL is required")
```

- [x] **Step 4: Run settings tests and regenerate the frozen lockfile**

Run: `uv lock && uv run pytest tests/test_postgres_settings.py -q --no-cov`

- [x] **Step 5: Commit**

Run: `git add backend/pyproject.toml backend/uv.lock backend/storage/settings.py backend/storage/postgres.py backend/tests/test_postgres_settings.py && git commit -m "feat: add PostgreSQL runtime settings"`

### Task 2: Models and Alembic baseline

**Files:**
- Create: `backend/storage/models.py`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_postgresql_v3_baseline.py`, `backend/tests/test_alembic.py`

**Interfaces:**
- Produces `Base.metadata`, `alembic_heads() -> list[str]`, and `current_revision(connection) -> str | None`.

- [x] **Step 1: Write failing empty-upgrade and one-head tests**

```python
def test_empty_postgres_upgrades_to_the_only_head(postgres_url):
    upgrade(postgres_url, "head")
    assert current_revision(connect(postgres_url)) == "0001_postgresql_v3_baseline"
    assert schemas(connect(postgres_url)) >= {"app", "auth"}

def test_alembic_has_one_head():
    assert alembic_heads() == ["0001_postgresql_v3_baseline"]
```

- [x] **Step 2: Run the tests and observe missing Alembic/model failures**

Run: `uv run pytest tests/test_alembic.py -q --no-cov`

- [x] **Step 3: Define app/auth ORM tables and baseline DDL**

The revision must create both schemas and all tables named in the spec, JSONB columns, primary/foreign keys, indexes, `app.alembic_version`, and no historical data transforms.

- [x] **Step 4: Run Alembic tests against disposable PostgreSQL**

Run: `uv run pytest tests/test_alembic.py -q --no-cov`

- [x] **Step 5: Commit**

Run: `git add backend/storage/models.py backend/alembic.ini backend/alembic backend/tests/test_alembic.py && git commit -m "feat: add PostgreSQL Alembic baseline"`

### Task 3: Business repositories and legacy adapters

**Files:**
- Create: `backend/storage/repositories/business.py`, `backend/tests/test_business_repository.py`
- Modify: `backend/storage/db.py`, `backend/storage/up_obs_reader.py`, `backend/storage/up_trends_reader.py`, `backend/storage/video_snapshot_reader.py`, `backend/storage/up_card_store.py`

**Interfaces:**
- Produces `BusinessRepository.record_video`, `record_observation`, `upsert_up_observations`, `claim_calendar_item`, and existing public storage functions delegated to it.

- [x] **Step 1: Write failing repository behavior tests**

```python
def test_video_observation_upsert_preserves_null_and_zero(repository):
    repository.record_observation("BV1", 100, {"views": None, "likes": 0})
    assert repository.video_trend("BV1", 48) == [{"ts": 100, "views": None, "likes": 0}]

def test_two_workers_claim_distinct_calendar_items(repository):
    repository.enqueue_calendar_items("job", [1, 2])
    assert {repository.claim_calendar_item("a")["mid"], repository.claim_calendar_item("b")["mid"]} == {1, 2}
```

- [x] **Step 2: Run tests and observe absent repository failures**

Run: `uv run pytest tests/test_business_repository.py -q --no-cov`

- [x] **Step 3: Implement repository transactions using `on_conflict_do_update` and `FOR UPDATE SKIP LOCKED`**

```python
stmt = insert(VideoObservation).values(**row).on_conflict_do_update(
    index_elements=[VideoObservation.bvid, VideoObservation.ts], set_=row
)
claimed = session.execute(select(CalendarItem).with_for_update(skip_locked=True).limit(1)).scalar_one_or_none()
```

- [x] **Step 4: Run repository and existing reader tests**

Run: `uv run pytest tests/test_business_repository.py tests/test_calendar_reliability.py -q --no-cov`

- [x] **Step 5: Commit**

Run: `git add backend/storage/repositories backend/storage/db.py backend/storage/up_obs_reader.py backend/storage/up_trends_reader.py backend/storage/video_snapshot_reader.py backend/storage/up_card_store.py backend/tests/test_business_repository.py && git commit -m "feat: move business storage to PostgreSQL"`

### Task 4: Auth, dashboard, favorites, and tracked-UP repositories

**Files:**
- Create: `backend/storage/repositories/auth.py`, `backend/storage/repositories/state.py`, `backend/tests/test_auth_repository.py`, `backend/tests/test_state_repository.py`
- Modify: `backend/storage/auth_store.py`, `backend/storage/database.py`, `backend/storage/tracked_ups.py`, `backend/storage/cache.py`, `backend/storage/repositories/state.py`
- Adapt legacy API tests and fixtures to PostgreSQL: `backend/tests/conftest.py`, auth/access-control/request/calendar/handoff tests

**Interfaces:**
- Produces adapter-compatible admin/session/handoff, favorite/dashboard, and tracked-UP/request functions.

- [x] **Step 1: Write failing state and auth tests**

```python
def test_review_request_is_atomic_and_adds_one_tracked_up(state_repository):
    request_id = state_repository.create_tracking_request(99, "visitor", "")
    assert state_repository.review_tracking_request(request_id, "approve")["added_to_pool"] is True
    assert state_repository.tracked_mids() == [99]

def test_session_result_never_contains_cookie(auth_repository):
    token = auth_repository.create_session("v", 1, "n", "f", {"SESSDATA": "secret"})
    assert "cookies" not in auth_repository.get_session(token)
```

- [x] **Step 2: Run tests and observe missing repository failures**

Run: `uv run pytest tests/test_auth_repository.py tests/test_state_repository.py -q --no-cov`

- [x] **Step 3: Implement row-locked mutations and JSONB state reads**

All adapter functions must stop importing `sqlite3`, opening JSON files, creating lock files, or using mtime as durable state.

- [x] **Step 4: Run focused and existing authorization/request tests**

Run: `uv run pytest tests/test_storage_adapters_require_postgres.py tests/test_alembic.py tests/test_auth_repository.py tests/test_state_repository.py tests/test_business_repository.py tests/test_access_control.py tests/test_admin_identity.py tests/test_up_requests.py tests/test_proxy_and_session_security.py tests/test_collector_handoff.py tests/test_calendar_api.py -q --no-cov`

- [x] **Step 5: Commit**

Commit: `feat: move auth and state to PostgreSQL`

### Task 5: No-DDL application startup, heartbeat, and readiness

**Files:**
- Create: `backend/storage/health.py`, `backend/tests/test_readiness.py`
- Modify: `backend/app.py`, `backend/api_entrypoint.py`, `backend/worker_entrypoint.py`, `backend/jobs/scheduler.py`

**Interfaces:**
- Produces `/api/health/live`, `/api/health/ready`, `HeartbeatService.start()`, and legacy `/api/health` readiness delegation.

- [x] **Step 1: Write failing health tests**

```python
def test_ready_returns_503_for_stale_worker(client, readiness):
    readiness.worker_age_seconds = 121
    assert client.get("/api/health/ready").status_code == 503

def test_importing_application_emits_no_ddl(monkeypatch):
    monkeypatch.setattr("sqlalchemy.engine.Connection.execute", fail_on_ddl)
    import_fresh("api_entrypoint")
```

- [x] **Step 2: Run tests and observe missing endpoints/service failures**

Run: `uv run pytest tests/test_readiness.py -q --no-cov`

- [x] **Step 3: Implement safe readiness checks and 30-second heartbeat refresh**

Readiness exposes reason codes only; it never returns URLs, credentials, cookies, or session content.

- [x] **Step 4: Run health and entrypoint tests**

Run: `uv run pytest tests/test_readiness.py tests/test_entrypoint_separation.py tests/test_secret_loading.py -q --no-cov`

- [x] **Step 5: Commit**

Run: `git add backend/storage/health.py backend/app.py backend/api_entrypoint.py backend/worker_entrypoint.py backend/jobs/scheduler.py backend/tests/test_readiness.py && git commit -m "feat: add PostgreSQL readiness and worker heartbeat"`

### Task 6: Offline snapshot importer and backfill command

**Files:**
- Create: `backend/scripts/import_sqlite_snapshot.py`, `backend/scripts/run_backfill.py`, `backend/tests/fixtures/import/`, `backend/tests/test_sqlite_snapshot_import.py`

**Interfaces:**
- Produces `import_snapshot(args) -> dict` and `reconcile_import(...) -> dict`.

- [x] **Step 1: Write failing import tests with read-only SQLite fixtures**

```python
def test_importer_reconciles_sqlite_and_json_snapshots(postgres_url, fixture_paths, tmp_path):
    report = import_snapshot(*fixture_paths, database_url=postgres_url, report_path=tmp_path / "report.json")
    assert report["valid"] is True
    assert report["entities"]["admins"]["source_count"] == 1

def test_importer_refuses_nonempty_target(postgres_url, fixture_paths):
    import_snapshot(*fixture_paths, database_url=postgres_url)
    with pytest.raises(ImportSafetyError, match="nonempty"):
        import_snapshot(*fixture_paths, database_url=postgres_url)
```

- [x] **Step 2: Run tests and observe importer-not-found failures**

Run: `uv run pytest tests/test_sqlite_snapshot_import.py -q --no-cov`

- [x] **Step 3: Implement explicit read-only source opening, ordered import, report, and resumable backfill claims**

Use `sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)` and never load any runtime default path.

- [x] **Step 4: Run importer tests**

Run: `uv run pytest tests/test_sqlite_snapshot_import.py -q --no-cov`

- [x] **Step 5: Commit**

Run: `git add backend/scripts/import_sqlite_snapshot.py backend/scripts/run_backfill.py backend/tests/fixtures/import backend/tests/test_sqlite_snapshot_import.py && git commit -m "feat: import SQLite snapshots into PostgreSQL"`

### Task 7: Migration command, Docker topology, backups, and CI

**Files:**
- Create: `backend/scripts/migrate.py`, `ops/postgres/init-roles.sh`, `ops/backup/backup_postgres.py`, `ops/backup/restore_drill.py`, `.github/workflows/backend.yml`, `backend/tests/test_postgres_operations.py`
- Modify: `compose.dev.yml`, `compose.prod.yml`, `backend/Dockerfile`, `.env.example`, `ops/backup/README.md`

**Interfaces:**
- Produces `python scripts/migrate.py`, custom dump manifest, restore drill, and Compose services `postgres`, `migrate`, `backup`.

- [x] **Step 1: Write failing Compose and backup behavior tests**

```python
def test_production_postgres_has_no_host_port_and_core_only(compose):
    assert "ports" not in compose["services"]["postgres"]
    assert compose["networks"]["core"]["internal"] is True

def test_backup_manifest_and_custom_dump_are_verified(fake_pg_tools, tmp_path):
    manifest = create_postgres_backup(fake_pg_tools, tmp_path, "rev", "tag", "digest")
    assert manifest["sha256"]
    assert fake_pg_tools.restore_list_called
```

- [x] **Step 2: Run tests and observe absent service/script failures**

Run: `uv run pytest tests/test_postgres_operations.py -q --no-cov`

- [x] **Step 3: Implement role-secret mounts, one-shot migration verification, custom dumps, checksum/manifest, and temporary-database restore drill**

Production must bind `${KICHU_HOST_POSTGRES_DIR}:/var/lib/postgresql/data`, never use a project data volume, and give API no egress network.

- [x] **Step 4: Run operational tests and Compose config validation**

Run: `uv run pytest tests/test_postgres_operations.py tests/test_compose_security.py -q --no-cov && docker compose -f compose.dev.yml config && docker compose -f compose.prod.yml config`

- [x] **Step 5: Commit**

Run: `git add compose.dev.yml compose.prod.yml backend/Dockerfile .env.example ops/postgres ops/backup backend/scripts/migrate.py backend/tests/test_postgres_operations.py .github/workflows/backend.yml && git commit -m "feat: add PostgreSQL operations and CI"`

### Task 8: Remove runtime SQLite/JSON persistence and document cutover

**Files:**
- Modify: `README.md`, `docs/deployment.md`, `docs/backup-restore.md`, `docs/migration-v2-to-v3.md`, all remaining `backend/storage` adapters and tests
- Create: `docs/postgresql-cutover.md`, `backend/tests/test_no_runtime_sqlite_or_json.py`

**Interfaces:**
- Produces an executable offline cutover and forward-only release runbook.

- [ ] **Step 1: Write failing production-path test**

```python
def test_production_runtime_never_opens_sqlite_or_state_json(monkeypatch, production_env):
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("SQLite runtime access"))
    assert create_app(production_env).test_client().get("/api/health/live").status_code == 200
```

- [ ] **Step 2: Run test and observe remaining SQLite/JSON adapter failure**

Run: `uv run pytest tests/test_no_runtime_sqlite_or_json.py -q --no-cov`

- [ ] **Step 3: Delete obsolete runtime persistence code and update documentation**

Documents must give the ten requested first-cutover steps, eight forward-release steps, source snapshot retention period, backup/restore commands, and the no-auto-downgrade rule.

- [ ] **Step 4: Run full available verification**

Run: `uv run pytest -q --no-cov && docker compose -f compose.dev.yml config && docker compose -f compose.prod.yml config`

- [ ] **Step 5: Commit**

Run: `git add README.md docs backend && git commit -m "docs: document PostgreSQL cutover and remove SQLite runtime"`
