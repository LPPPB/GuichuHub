# PostgreSQL Architecture Refactor Design

## Goal

Make PostgreSQL 16 the sole production persistence system for V3. SQLite snapshots and the two mutable JSON files become one-time, explicit, read-only import inputs. API and Worker retain their existing API contracts but never create schema, run migrations, or persist application state in files.

## Non-goals

- No production deployment, production database access, production data import, backup deletion, or automatic downgrade is performed by this change.
- The cutover is offline and may use an unlimited maintenance window. There is no SQLite/PostgreSQL dual write or zero-downtime compatibility mode.
- Cookie files remain an explicitly scoped private runtime handoff only until their contents have been imported into `auth.collector_credential_handoffs`; they are not an application state store.

## Configuration and trust boundaries

Python remains 3.12. The backend adds SQLAlchemy 2.x, Alembic, psycopg 3, and PostgreSQL 16.

Every process loads exactly one URL from an explicit file path. `KICHU_API_DATABASE_URL_FILE`, `KICHU_WORKER_DATABASE_URL_FILE`, and `KICHU_MIGRATION_DATABASE_URL_FILE` identify distinct protected files. `KICHU_DATABASE_URL_FILE` is accepted only by offline tools and tests. URLs are parsed with SQLAlchemy and rejected unless the dialect is `postgresql` or `postgresql+psycopg`. Values, passwords, cookies, sessions, and complete URLs are never logged.

The API and Worker use distinct least-privilege login roles. The migration role owns `app` and `auth` and is the only role with DDL privileges. The backup role can read enough data for `pg_dump` but has no schema-changing grants. Docker secrets mount role URLs and passwords as files; development may use files below ignored `runtime/dev/secrets`, and production uses protected paths outside the checkout.

## Schema ownership and data model

Alembic is the only DDL authority. It has one revision head, writes its version row in `app.alembic_version`, and creates the `app` and `auth` schemas. Baseline revision `0001_postgresql_v3_baseline` represents all current V3 SQLite V1–V11 structures without replaying their historical SQLite migration code.

`app` contains `videos`, `ups`, `video_observations`, `video_tags`, `word_observations`, `crawl_runs`, `up_observations`, `up_staff_memberships`, `video_snapshot_documents` (JSONB), `calendar_videos`, `calendar_video_authors`, `calendar_backfill_jobs`, `calendar_backfill_job_items`, `dashboard_state`, `favorites`, `tracked_ups`, `tracked_up_settings`, `tracking_requests`, `up_card_cache`, `data_import_records`, `backfill_progress`, and `worker_heartbeats`.

`auth` contains `admin_accounts`, `browser_sessions`, and `collector_credential_handoffs`. Cookie-bearing data never leaves storage as an HTTP response and is never logged.

All timestamps preserve existing epoch-second API semantics. Nullable source metrics remain nullable: `NULL` means unknown and `0` means observed zero. Documents migrate to JSONB. Natural source keys remain stable (`bvid`, `mid`, legacy favorite id, handoff id); new internal rows use UUID or identity keys only where there is no source identity.

Foreign keys, check constraints, and indexes live in the baseline. Idempotent writes use PostgreSQL `INSERT ... ON CONFLICT`; claim operations use `SELECT ... FOR UPDATE SKIP LOCKED` inside short transactions.

## Repository boundary

`storage/db.py`, `auth_store.py`, `database.py`, `tracked_ups.py`, cache and reader modules keep their public functions during the refactor, but become thin adapters over focused repositories. Business code receives repository interfaces or application services; it does not receive SQLAlchemy sessions or use ad-hoc SQL. The engine/session lifecycle is centralized in `storage/postgres.py`.

Dashboard state updates, favorite mutation, tracked-UP changes, request review, credential handoff claiming, and calendar job claiming use database transactions and row locks. The only surviving in-memory cache is an optional process-local read-through cache whose invalidation is a database revision/version, never a JSON mtime. It is not a persistence source.

## Startup, Worker, and readiness

Importing or starting API/Worker opens no SQLite database and runs no DDL. `api_entrypoint.py` owns HTTP only. `worker_entrypoint.py` owns scheduling, job workers, and a heartbeat loop that upserts `app.worker_heartbeats` at startup and at least every 30 seconds.

`GET /api/health/live` proves only that Flask is running. `GET /api/health/ready` checks a PostgreSQL query, exactly one Alembic head and current revision equality, and a Worker heartbeat no older than 120 seconds. Any failed condition returns 503 and a safe reason code. The legacy `/api/health` delegates to readiness.

`backend/scripts/migrate.py` requires the migration URL file, executes `alembic upgrade head`, then confirms the sole head equals the applied revision. It never contacts production unless an operator explicitly supplies a production secret file.

## Offline import and backfills

`backend/scripts/import_sqlite_snapshot.py` accepts only named `--business-sqlite`, `--auth-sqlite`, `--dashboard-json`, and `--tracked-ups-json` inputs. SQLite is opened with `mode=ro`; it never derives paths from runtime configuration. It refuses a nonempty target unless `--allow-nonempty` is supplied and writes a JSON reconciliation report at `--report`.

The importer loads principals, video/UP entities, observations/documents/calendar data, auth entities/handoffs, dashboard/favorites, then tracked configuration/requests. It normalizes SQLite nulls, numeric zeroes, epoch timestamps, JSON text, and source primary keys without inventing values. It records a resumable idempotent import record and reports source/target counts, key-set comparisons, latest observation timestamp, admin/session/handoff/favorite/tracked counts, dashboard validation, and final `valid`.

Large historical recalculation is not an Alembic migration. A resumable `backfill_progress` job claims chunks with `SKIP LOCKED`, commits each chunk, records checkpoints/errors, and can be rerun safely.

## Compose, backup, and restore

Development and production Compose add `postgres:16`. Production exposes no PostgreSQL host port and mounts `${KICHU_HOST_POSTGRES_DIR}` outside the checkout at `/var/lib/postgresql/data`. `postgres`, API, Worker, migrate, and backup attach to internal `core`; API also joins `edge` for Caddy but not `egress`; Worker joins `egress`; frontend/Caddy remain at the edge.

Production includes one-shot `migrate` and maintenance `backup` services. Postgres initialization creates distinct roles from mounted Docker secrets. Backup invokes `pg_dump --format=custom`, writes SHA-256 and a manifest with timestamp, Git tag, image digest, and Alembic revision, and checks the dump with `pg_restore --list`. The restore drill restores into a newly created temporary database, verifies schema/revision, and performs an application read-only probe. No backup artifact is committed or automatically removed.

## Delivery and verification

Each implementation phase follows RED, GREEN, verification, and a focused Git commit. Unit tests use temporary URL files. PostgreSQL repository/integration tests use a disposable PostgreSQL 16 service. CI checks Alembic's single head, empty-db upgrade, old fixture import, application no-DDL behavior, import reconciliation, readiness error paths, repositories, Compose security, and the existing backend suite.

The cutover runbook is explicit: stop writes; make and verify four source snapshots; start empty PostgreSQL; migrate; import; review reconciliation; change configuration; rerun migration as a no-op; start services; check readiness, heartbeat, core APIs, and logs; retain source snapshots read-only. Subsequent releases back up, stop writers, migrate forward, start, and verify. Downgrade is forbidden; forward repair is preferred and restore requires an approved maintenance window.
