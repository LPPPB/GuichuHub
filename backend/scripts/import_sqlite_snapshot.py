"""One-shot, offline importer for explicitly supplied V3 SQLite/JSON snapshots.

This tool never discovers a runtime path, never opens a source for writing, and
never runs DDL.  Operators must first migrate an empty PostgreSQL database with
Alembic, then invoke this script with four deliberate snapshot paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from storage.postgres import create_engine
from sqlalchemy.dialects.postgresql import insert
from storage.migrations import alembic_heads

from storage.models import (
    admin_accounts, browser_sessions, calendar_backfill_job_items,
    calendar_backfill_jobs, calendar_video_authors, calendar_videos,
    collector_credential_handoffs, crawl_runs, dashboard_state,
    data_import_records, favorites, tracked_up_settings, tracked_ups,
    tracking_requests, up_card_cache, up_observations, up_staff_memberships,
    ups, video_observations, video_snapshot_documents, video_tags, videos,
    word_observations,
)


class ImportSafetyError(RuntimeError):
    """Raised before an import would write to an unsafe target."""


_TARGET_DATA_TABLES = (
    videos, ups, video_observations, video_tags, word_observations, crawl_runs,
    up_observations, up_staff_memberships, video_snapshot_documents,
    calendar_videos, calendar_video_authors, calendar_backfill_jobs,
    calendar_backfill_job_items, dashboard_state, favorites, tracked_ups,
    tracked_up_settings, tracking_requests, up_card_cache,
    admin_accounts, browser_sessions, collector_credential_handoffs,
)


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        result = value if isinstance(value, (dict, list)) else json.loads(value)
    except (TypeError, json.JSONDecodeError):
        raise ImportSafetyError("invalid embedded JSON in snapshot") from None
    if not isinstance(result, type(default)):
        raise ImportSafetyError("invalid embedded JSON type in snapshot")
    return result


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImportSafetyError(f"cannot read JSON snapshot: {path.name}") from error
    if not isinstance(payload, dict):
        raise ImportSafetyError(f"JSON snapshot must contain an object: {path.name}")
    return payload


def _open_sqlite_readonly(path: Path) -> sqlite3.Connection:
    path = Path(path)
    if not path.is_file():
        raise ImportSafetyError(f"SQLite snapshot does not exist: {path}")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _rows(connection: sqlite3.Connection, table: str) -> list[dict]:
    found = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if found is None:
        return []
    return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]


def _fingerprint(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _upsert(connection, table, rows: list[dict], keys: list):
    if not rows:
        return
    _remember(connection, table, rows)
    # Leave ample headroom below PostgreSQL's 65,535 bind limit, independent
    # of table width. Bound statements even when the source history is large.
    batch_size = min(1000, 60000 // len(table.columns))
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset:offset + batch_size]
        statement = insert(table).values(batch)
        updates = {name: getattr(statement.excluded, name) for name in batch[0]
                   if name not in {column.name for column in keys}}
        statement = (statement.on_conflict_do_update(index_elements=keys, set_=updates)
                     if updates else statement.on_conflict_do_nothing(index_elements=keys))
        connection.execute(statement)


def _remember(connection, table, rows, synthesized=False):
    expected = connection.info.setdefault("import_expected", {}).setdefault(table.name, {})
    synthetic = connection.info.setdefault("import_synthesized", {}).setdefault(table.name, set())
    for row in rows:
        key = tuple(row[column.name] for column in table.primary_key.columns)
        if synthesized and key in expected:
            continue
        expected[key] = dict(row)
        if synthesized:
            synthetic.add(key)


def _reconcile(connection):
    reports = {}
    for table in _TARGET_DATA_TABLES:
        expected = connection.info["import_expected"].get(table.name, {})
        actual = {tuple(row[column.name] for column in table.primary_key.columns): dict(row)
                  for row in connection.execute(select(table)).mappings()}
        reports[table.name] = {
            **_collection_report(expected, actual),
            "synthesized_count": len(connection.info.get("import_synthesized", {}).get(table.name, set())),
            "payloads_match": all(key in actual and all(actual[key][field] == value for field, value in row.items())
                                  for key, row in expected.items()),
        }
    return reports


def _ensure_video(connection, bvid: str, mid: int | None, first_seen: int) -> None:
    _remember(connection, videos, [{"bvid": bvid, "mid": mid, "title": "", "first_seen": first_seen,
                                   "source": "sqlite-import", "observe_tier": "cold"}], synthesized=True)
    connection.execute(insert(videos).values(
        bvid=bvid, mid=mid, title="", first_seen=first_seen, source="sqlite-import",
        observe_tier="cold",
    ).on_conflict_do_nothing(index_elements=[videos.c.bvid]))


def _ensure_up(connection, mid: int) -> None:
    _remember(connection, ups, [{"mid": mid, "tracked": False}], synthesized=True)
    connection.execute(insert(ups).values(mid=mid, tracked=False).on_conflict_do_nothing(
        index_elements=[ups.c.mid]
    ))


def _require_migrated_empty_target(connection, allow_nonempty: bool) -> None:
    try:
        revision = connection.execute(text("SELECT version_num FROM app.alembic_version")).scalar_one_or_none()
    except Exception as error:
        raise ImportSafetyError("target must be initialized with alembic upgrade head") from error
    if [revision] != alembic_heads():
        raise ImportSafetyError("target Alembic revision is not current")
    if allow_nonempty:
        return
    for table in _TARGET_DATA_TABLES:
        if connection.execute(select(table.c[list(table.primary_key.columns)[0].name]).limit(1)).first():
            raise ImportSafetyError("target database is nonempty; pass --allow-nonempty only for a reviewed retry")


def _import_business(connection, source: sqlite3.Connection) -> dict[str, Any]:
    source_videos = _rows(source, "videos")
    source_ups = _rows(source, "ups")
    for row in source_videos:
        row["observe_tier"] = row.get("observe_tier") or "hot"
        row["first_seen"] = row.get("first_seen") or 0
    _upsert(connection, videos, source_videos, [videos.c.bvid])
    for row in source_ups:
        row["tracked"] = bool(row.get("tracked", False))
    _upsert(connection, ups, source_ups, [ups.c.mid])

    observations = _rows(source, "video_obs")
    for row in observations:
        _ensure_video(connection, row["bvid"], None, int(row.get("ts") or 0))
    _upsert(connection, video_observations, observations, [video_observations.c.bvid, video_observations.c.ts])
    tags = _rows(source, "video_tags")
    for row in tags:
        _ensure_video(connection, row["bvid"], None, int(row.get("ts") or 0))
    _upsert(connection, video_tags, tags, [video_tags.c.bvid, video_tags.c.tag])
    words = _rows(source, "word_obs")
    _upsert(connection, word_observations, words, [word_observations.c.word, word_observations.c.ts, word_observations.c.scope])

    crawls = _rows(source, "crawl_runs")
    for row in crawls:
        row["stats"] = _json(row.pop("stats_json", None), {})
    _upsert(connection, crawl_runs, crawls, [crawl_runs.c.id])
    _reseed(connection, crawl_runs)

    up_rows = _rows(source, "up_obs")
    for row in up_rows:
        _ensure_up(connection, int(row["mid"]))
        latest_videos = _json(row.pop("latest_videos_json", None), [])
        payload = dict(row)
        payload["latest_videos"] = latest_videos
        for old, new in {"kichu_count": "kichu_video_count", "video_count_30d": "recent_video_count",
                         "views_30d": "total_recent_views", "latest_pub_ts": "latest_pub_date",
                         "video_count_total": "video_count", "kichu_count_30d": "recent_kichu_count"}.items():
            if old in payload:
                payload[new] = payload.pop(old)
        row.clear()
        row.update({"mid": payload["mid"], "ts": payload["ts"], "payload": payload})
    _upsert(connection, up_observations, up_rows, [up_observations.c.mid, up_observations.c.ts])

    staff = _rows(source, "up_staff_map")
    for row in staff:
        _ensure_video(connection, row["bvid"], None, 0)
        _ensure_up(connection, int(row["mid"]))
    _upsert(connection, up_staff_memberships, staff, [up_staff_memberships.c.bvid, up_staff_memberships.c.mid])

    snapshots = _rows(source, "video_obs_snapshot")
    for row in snapshots:
        row["payload"] = _json(row.pop("payload_json", None),
                               {} if row["field"] == "pool_summary" else [])
        row["item_count"] = row.get("item_count") or len(row["payload"])
    _upsert(connection, video_snapshot_documents, snapshots, [video_snapshot_documents.c.ts, video_snapshot_documents.c.field])

    cards = _rows(source, "up_card_cache")
    for row in cards:
        row["payload"] = _json(row.pop("payload_json", None), {})
    _upsert(connection, up_card_cache, cards, [up_card_cache.c.mid])

    calendar = _rows(source, "calendar_videos")
    for row in calendar:
        _ensure_video(connection, row["bvid"], row["mid"], int(row.get("pub_date") or 0))
        _ensure_up(connection, int(row["mid"]))
        row.setdefault("fetched_at", 0); row.setdefault("last_seen_at", 0)
        row.setdefault("missing_count", 0); row.setdefault("status", "active")
    canonical = {}
    for row in calendar:
        previous = canonical.get(row["bvid"])
        if previous is None or (row.get("views") or 0) > (previous.get("views") or 0):
            canonical[row["bvid"]] = row
    _upsert(connection, calendar_videos, list(canonical.values()), [calendar_videos.c.bvid])
    calendar_authors = _rows(source, "calendar_video_authors")
    author_rows = {(row["bvid"], row["mid"]): {"bvid": row["bvid"], "mid": row["mid"],
                    "last_seen_at": row.get("last_seen_at", 0), "missing_count": row.get("missing_count", 0),
                    "status": row.get("status", "active")} for row in calendar}
    author_rows.update({(row["bvid"], row["mid"]): row for row in calendar_authors})
    calendar_authors = list(author_rows.values())
    for row in calendar_authors:
        _ensure_video(connection, row["bvid"], row["mid"], 0)
        _ensure_up(connection, int(row["mid"]))
        row.setdefault("last_seen_at", 0); row.setdefault("missing_count", 0); row.setdefault("status", "active")
    _upsert(connection, calendar_video_authors, calendar_authors, [calendar_video_authors.c.bvid, calendar_video_authors.c.mid])

    jobs = _rows(source, "calendar_backfill_jobs")
    for row in jobs:
        payload = dict(row)
        row.clear()
        row.update({"id": str(payload["id"]), "mode": payload.get("mode") or "legacy",
                    "status": payload.get("status") or "queued", "payload": payload,
                    "created_at": payload.get("created_at") or 0, "updated_at": payload.get("updated_at") or 0,
                    "lease_until": payload.get("lease_until"), "worker_id": payload.get("worker_id")})
    _upsert(connection, calendar_backfill_jobs, jobs, [calendar_backfill_jobs.c.id])
    items = _rows(source, "calendar_backfill_job_items")
    for row in items:
        payload = dict(row)
        row.clear()
        row.update({"job_id": str(payload["job_id"]), "mid": payload["mid"],
                    "status": payload.get("status") or "queued", "worker_id": payload.get("worker_id"),
                    "payload": payload})
    _upsert(connection, calendar_backfill_job_items, items, [calendar_backfill_job_items.c.job_id, calendar_backfill_job_items.c.mid])
    return {
        "videos": len(source_videos), "video_observations": len(observations),
        "ups": len(source_ups), "up_observations": len(up_rows),
        "_keys": {
            "videos": [row["bvid"] for row in source_videos],
            "video_observations": [(row["bvid"], row["ts"]) for row in observations],
            "ups": [row["mid"] for row in source_ups],
            "up_observations": [(row["mid"], row["ts"]) for row in up_rows],
        },
    }


def _reseed(connection, table):
    # Never move a sequence backwards on a reviewed retry.
    maximum = connection.execute(select(func.max(table.c.id))).scalar_one()
    if maximum is not None:
        sequence = f"{table.schema}.{table.name}_id_seq"
        last = connection.execute(text(f"SELECT last_value FROM {sequence}")).scalar_one()
        connection.execute(text("SELECT setval(pg_get_serial_sequence(:table, 'id'), :value, true)"),
                           {"table": table.fullname, "value": max(maximum, last)})


def _import_auth(connection, source: sqlite3.Connection) -> dict[str, Any]:
    admins = _rows(source, "admin_accounts")
    _upsert(connection, admin_accounts, admins, [admin_accounts.c.mid])
    sessions = _rows(source, "bili_sessions")
    for row in sessions:
        row["cookies"] = _json(row.get("cookies"), {})
    _upsert(connection, browser_sessions, sessions, [browser_sessions.c.token])
    handoffs = _rows(source, "collector_credential_handoffs")
    for row in handoffs:
        row["payload"] = _json(row.get("payload"), {})
    _upsert(connection, collector_credential_handoffs, handoffs, [collector_credential_handoffs.c.id])
    _reseed(connection, collector_credential_handoffs)
    return {
        "admins": len(admins), "sessions": len(sessions),
        "credential_handoffs": len(handoffs),
        "_keys": {
            "admins": [row["mid"] for row in admins],
            "sessions": [row["token"] for row in sessions],
            "credential_handoffs": [row["id"] for row in handoffs],
        },
    }


def _import_json_state(connection, dashboard: dict, tracked: dict, now: int) -> dict[str, Any]:
    dashboard_payload = dashboard.get("dashboard") if isinstance(dashboard.get("dashboard"), dict) else dashboard
    runtime_settings = dashboard.get("runtime_settings") if isinstance(dashboard.get("runtime_settings"), dict) else {}
    _remember(connection, dashboard_state, [{"name": "current", "payload": dashboard_payload}])
    connection.execute(insert(dashboard_state).values(name="current", payload=dashboard_payload, version=1, updated_at=now)
                       .on_conflict_do_update(index_elements=[dashboard_state.c.name], set_={"payload": dashboard_payload, "updated_at": now}))
    for name in ("danmaku_filters", "meme_stopwords", "meme_seed_words", "tag_filters"):
        if name not in runtime_settings:
            continue
        _remember(connection, dashboard_state, [{"name": name, "payload": runtime_settings[name]}])
        connection.execute(insert(dashboard_state).values(
            name=name, payload=runtime_settings[name], version=1, updated_at=now,
        ).on_conflict_do_update(
            index_elements=[dashboard_state.c.name],
            set_={"payload": runtime_settings[name], "updated_at": now},
        ))
    favorite_rows = []
    for item in dashboard_payload.get("favorites", []):
        if not isinstance(item, dict):
            raise ImportSafetyError("invalid favorite object in snapshot")
        value = dict(item)
        saved_at = value.get("saved_at")
        if saved_at is None or saved_at == "":
            saved_at = now
        try:
            saved_at = int(saved_at)
        except (ValueError, TypeError):
            saved_at = int(datetime.strptime(saved_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=8))).timestamp())
        value["saved_at"] = datetime.fromtimestamp(saved_at, timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        value["id"] = str(value.get("id") or "import_" + hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest())
        favorite_rows.append({"id": value["id"],
                              "owner": str(value.get("owner") or ""), "item_type": str(value.get("type") or "unknown"),
                              "item": value, "tags": value.get("tags") or [], "notes": value.get("notes") or "",
                              "saved_at": saved_at})
    _upsert(connection, favorites, favorite_rows, [favorites.c.id])
    tracked_rows = []
    for item in tracked.get("ups", []):
        if isinstance(item, dict) and item.get("mid") is not None:
            tracked_rows.append({"mid": int(item["mid"]), "payload": item,
                                 "enabled": bool(item.get("enabled", True)), "updated_at": int(tracked.get("updated_at") or now)})
    _upsert(connection, tracked_ups, tracked_rows, [tracked_ups.c.mid])
    config = tracked.get("config") if isinstance(tracked.get("config"), dict) else {}
    _remember(connection, tracked_up_settings, [{"name": "tracked_list", "payload": {"config": config}}])
    connection.execute(insert(tracked_up_settings).values(name="tracked_list", payload={"config": config}, updated_at=int(tracked.get("updated_at") or now))
                       .on_conflict_do_update(index_elements=[tracked_up_settings.c.name], set_={"payload": {"config": config}, "updated_at": int(tracked.get("updated_at") or now)}))
    requests = []
    raw_requests = tracked.get("requests") if isinstance(tracked.get("requests"), dict) else {}
    for item in list(raw_requests.get("pending") or []) + list(raw_requests.get("processed") or []):
        if not isinstance(item, dict) or not item.get("id") or item.get("mid") is None or not item.get("visitor_id"):
            continue
        requests.append({"id": str(item["id"]), "mid": int(item["mid"]), "visitor_id": str(item["visitor_id"]),
                         "status": str(item.get("status") or "pending"),
                         "payload": {"up": item.get("up") or {}, "reason": item.get("reason") or "",
                                     "reject_reason": item.get("reject_reason") or "",
                                     "request_type": item.get("request_type") or "add"},
                         "created_at": int(item.get("submitted_at") or now), "reviewed_at": item.get("reviewed_at")})
    _upsert(connection, tracking_requests, requests, [tracking_requests.c.id])
    return {
        "favorites": len(favorite_rows), "tracked_ups": len(tracked_rows),
        "tracking_requests": len(requests), "runtime_settings": len(runtime_settings),
        "_keys": {
            "favorites": [row["id"] for row in favorite_rows],
            "tracked_ups": [row["mid"] for row in tracked_rows],
            "tracking_requests": [row["id"] for row in requests],
            "runtime_settings": list(runtime_settings),
        },
    }


def _collection_report(source_keys, target_keys) -> dict[str, Any]:
    """Compare both row cardinality and complete primary-key identity."""
    source_keys = list(source_keys)
    target_keys = list(target_keys)
    return {
        "source_count": len(source_keys),
        "target_count": len(target_keys),
        "keys_match": set(source_keys) == set(target_keys),
    }


def import_snapshot(*, business_sqlite: Path, auth_sqlite: Path, dashboard_json: Path,
                    tracked_ups_json: Path, database_url: str, report_path: Path,
                    allow_nonempty: bool = False) -> dict:
    """Import four explicit offline snapshots and write a reconciliation JSON report."""
    paths = tuple(Path(path) for path in (business_sqlite, auth_sqlite, dashboard_json, tracked_ups_json))
    if not database_url.startswith("postgresql"):
        raise ImportSafetyError("PostgreSQL database URL is required")
    business_source = _open_sqlite_readonly(paths[0])
    auth_source = _open_sqlite_readonly(paths[1])
    dashboard = _read_json(paths[2])
    tracked = _read_json(paths[3])
    engine = create_engine(database_url, pool_pre_ping=True)
    now = int(time.time())
    fingerprint = _fingerprint(paths)
    try:
        with engine.begin() as connection:
            connection.info["import_expected"] = {}
            connection.info["import_synthesized"] = {}
            connection.execute(select(func.pg_advisory_xact_lock(func.hashtextextended("offline-snapshot-import", 0))))
            _require_migrated_empty_target(connection, allow_nonempty)
            business_counts = _import_business(connection, business_source)
            auth_counts = _import_auth(connection, auth_source)
            state_counts = _import_json_state(connection, dashboard, tracked, now)
            connection.execute(insert(data_import_records).values(
                id=str(uuid.uuid4()), source_fingerprint=fingerprint, status="running", report={}, created_at=now,
            ).on_conflict_do_update(index_elements=[data_import_records.c.source_fingerprint],
                                    set_={"status": "running", "report": {}}))
            latest_source = business_source.execute("SELECT MAX(ts) FROM video_obs").fetchone()[0] if _rows(business_source, "video_obs") else None
            latest_target = connection.execute(select(func.max(video_observations.c.ts))).scalar_one()
            dashboard_payload = dashboard.get("dashboard") if isinstance(dashboard.get("dashboard"), dict) else dashboard
            source_settings = dashboard.get("runtime_settings") if isinstance(dashboard.get("runtime_settings"), dict) else {}
            target_dashboard = connection.execute(select(dashboard_state.c.payload).where(
                dashboard_state.c.name == "current",
            )).scalar_one_or_none()
            target_settings = dict(connection.execute(select(
                dashboard_state.c.name, dashboard_state.c.payload,
            ).where(dashboard_state.c.name != "current")).all())
            entity_reports = {
                "videos": _collection_report(
                    business_counts["_keys"]["videos"],
                    connection.execute(select(videos.c.bvid)).scalars(),
                ),
                "video_observations": _collection_report(
                    business_counts["_keys"]["video_observations"],
                    (tuple(row) for row in connection.execute(select(
                        video_observations.c.bvid, video_observations.c.ts,
                    ))),
                ),
                "ups": _collection_report(
                    business_counts["_keys"]["ups"],
                    connection.execute(select(ups.c.mid)).scalars(),
                ),
                "up_observations": _collection_report(
                    business_counts["_keys"]["up_observations"],
                    (tuple(row) for row in connection.execute(select(
                        up_observations.c.mid, up_observations.c.ts,
                    ))),
                ),
                "admins": _collection_report(
                    auth_counts["_keys"]["admins"],
                    connection.execute(select(admin_accounts.c.mid)).scalars(),
                ),
            }
            entity_reports.update(_reconcile(connection))
            # Keep the historical report alias while the exhaustive table map
            # also uses the actual relation names.
            entity_reports["admins"] = entity_reports["admin_accounts"]
            sessions_report = _collection_report(
                auth_counts["_keys"]["sessions"],
                connection.execute(select(browser_sessions.c.token)).scalars(),
            )
            handoffs_report = _collection_report(
                auth_counts["_keys"]["credential_handoffs"],
                connection.execute(select(collector_credential_handoffs.c.id)).scalars(),
            )
            favorites_report = _collection_report(
                state_counts["_keys"]["favorites"],
                connection.execute(select(favorites.c.id)).scalars(),
            )
            tracked_ups_report = _collection_report(
                state_counts["_keys"]["tracked_ups"],
                connection.execute(select(tracked_ups.c.mid)).scalars(),
            )
            tracking_requests_report = _collection_report(
                state_counts["_keys"]["tracking_requests"],
                connection.execute(select(tracking_requests.c.id)).scalars(),
            )
            runtime_settings_report = _collection_report(
                state_counts["_keys"]["runtime_settings"], target_settings,
            )
            runtime_settings_report["payloads_match"] = target_settings == source_settings
            runtime_settings_report["matches"] = (
                runtime_settings_report["keys_match"]
                and runtime_settings_report["payloads_match"]
            )
            report = {
                "valid": False,
                "entities": entity_reports,
                "latest_observation_ts": {"source": latest_source, "target": latest_target},
                "sessions": sessions_report,
                "credential_handoffs": handoffs_report,
                "favorites": favorites_report,
                "tracked_ups": tracked_ups_report,
                "tracking_requests": tracking_requests_report,
                "dashboard_state": {"source_present": True, "target_present": target_dashboard is not None,
                                    "matches": target_dashboard == dashboard_payload},
                "runtime_settings": runtime_settings_report,
            }
            reconciled_collections = [
                *report["entities"].values(), report["sessions"],
                report["credential_handoffs"], report["favorites"],
                report["tracked_ups"], report["tracking_requests"],
            ]
            report["valid"] = (
                all(item["source_count"] == item["target_count"] and item["keys_match"] and item.get("payloads_match", True)
                    for item in reconciled_collections)
                and report["latest_observation_ts"]["source"] == report["latest_observation_ts"]["target"]
                and report["dashboard_state"]["target_present"]
                and report["dashboard_state"]["matches"]
                and report["runtime_settings"]["source_count"] == report["runtime_settings"]["target_count"]
                and report["runtime_settings"]["matches"]
            )
            report["conversion_errors"] = []
            connection.execute(data_import_records.update().where(data_import_records.c.source_fingerprint == fingerprint)
                               .values(report=report, status="completed" if report["valid"] else "invalid"))
    except ImportSafetyError as error:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({"valid": False, "conversion_errors": [str(error)]}), encoding="utf-8")
        raise
    finally:
        business_source.close()
        auth_source.close()
        engine.dispose()
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import explicit offline V3 snapshots into migrated PostgreSQL")
    parser.add_argument("--business-sqlite", required=True, type=Path)
    parser.add_argument("--auth-sqlite", required=True, type=Path)
    parser.add_argument("--dashboard-json", required=True, type=Path)
    parser.add_argument("--tracked-ups-json", required=True, type=Path)
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--allow-nonempty", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = _arguments()
    url = args.database_url_file.read_text(encoding="utf-8").strip()
    result = import_snapshot(
        business_sqlite=args.business_sqlite, auth_sqlite=args.auth_sqlite,
        dashboard_json=args.dashboard_json, tracked_ups_json=args.tracked_ups_json,
        database_url=url, report_path=args.report, allow_nonempty=args.allow_nonempty,
    )
    raise SystemExit(0 if result["valid"] else 2)
