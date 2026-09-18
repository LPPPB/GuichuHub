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
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert

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
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


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
    statement = insert(table).values(rows)
    updates = {
        column.name: getattr(statement.excluded, column.name)
        for column in table.columns if column not in keys
    }
    connection.execute(statement.on_conflict_do_update(index_elements=keys, set_=updates))


def _ensure_video(connection, bvid: str, mid: int | None, first_seen: int) -> None:
    connection.execute(insert(videos).values(
        bvid=bvid, mid=mid, title="", first_seen=first_seen, source="sqlite-import",
        observe_tier="cold",
    ).on_conflict_do_nothing(index_elements=[videos.c.bvid]))


def _ensure_up(connection, mid: int) -> None:
    connection.execute(insert(ups).values(mid=mid, tracked=False).on_conflict_do_nothing(
        index_elements=[ups.c.mid]
    ))


def _require_migrated_empty_target(connection, allow_nonempty: bool) -> None:
    try:
        revision = connection.execute(text("SELECT version_num FROM app.alembic_version")).scalar_one_or_none()
    except Exception as error:
        raise ImportSafetyError("target must be initialized with alembic upgrade head") from error
    if revision != "0001_postgresql_v3_baseline":
        raise ImportSafetyError("target Alembic revision is not the PostgreSQL baseline")
    if allow_nonempty:
        return
    for table in _TARGET_DATA_TABLES:
        if connection.execute(select(table.c[list(table.primary_key.columns)[0].name]).limit(1)).first():
            raise ImportSafetyError("target database is nonempty; pass --allow-nonempty only for a reviewed retry")


def _import_business(connection, source: sqlite3.Connection) -> dict[str, int]:
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

    up_rows = _rows(source, "up_obs")
    for row in up_rows:
        _ensure_up(connection, int(row["mid"]))
        latest_videos = _json(row.pop("latest_videos_json", None), [])
        payload = dict(row)
        payload["latest_videos"] = latest_videos
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
        row["payload"] = _json(row.pop("payload_json", None), [])
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
    _upsert(connection, calendar_videos, calendar, [calendar_videos.c.bvid, calendar_videos.c.mid])
    calendar_authors = _rows(source, "calendar_video_authors")
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
    return {"videos": len(source_videos), "video_observations": len(observations),
            "ups": len(source_ups), "up_observations": len(up_rows)}


def _import_auth(connection, source: sqlite3.Connection) -> dict[str, int]:
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
    if handoffs:
        connection.execute(text("SELECT setval(pg_get_serial_sequence('auth.collector_credential_handoffs', 'id'), :value, true)"),
                           {"value": max(row["id"] for row in handoffs)})
    return {"admins": len(admins), "sessions": len(sessions), "credential_handoffs": len(handoffs)}


def _import_json_state(connection, dashboard: dict, tracked: dict, now: int) -> dict[str, int]:
    dashboard_payload = dashboard.get("dashboard") if isinstance(dashboard.get("dashboard"), dict) else dashboard
    runtime_settings = dashboard.get("runtime_settings") if isinstance(dashboard.get("runtime_settings"), dict) else {}
    connection.execute(insert(dashboard_state).values(name="current", payload=dashboard_payload, version=1, updated_at=now)
                       .on_conflict_do_update(index_elements=[dashboard_state.c.name], set_={"payload": dashboard_payload, "updated_at": now}))
    for name in ("danmaku_filters", "meme_stopwords", "meme_seed_words", "tag_filters"):
        if name not in runtime_settings:
            continue
        connection.execute(insert(dashboard_state).values(
            name=name, payload=runtime_settings[name], version=1, updated_at=now,
        ).on_conflict_do_update(
            index_elements=[dashboard_state.c.name],
            set_={"payload": runtime_settings[name], "updated_at": now},
        ))
    favorite_rows = []
    for item in dashboard_payload.get("favorites", []):
        if not isinstance(item, dict):
            continue
        value = dict(item)
        favorite_rows.append({"id": str(value.get("id") or f"import_{uuid.uuid4().hex}"),
                              "owner": str(value.get("owner") or ""), "item_type": str(value.get("type") or "unknown"),
                              "item": value, "tags": value.get("tags") or [], "notes": value.get("notes") or "",
                              "saved_at": int(value.get("saved_at") or now)})
    _upsert(connection, favorites, favorite_rows, [favorites.c.id])
    tracked_rows = []
    for item in tracked.get("ups", []):
        if isinstance(item, dict) and item.get("mid") is not None:
            tracked_rows.append({"mid": int(item["mid"]), "payload": item,
                                 "enabled": bool(item.get("enabled", True)), "updated_at": int(tracked.get("updated_at") or now)})
    _upsert(connection, tracked_ups, tracked_rows, [tracked_ups.c.mid])
    config = tracked.get("config") if isinstance(tracked.get("config"), dict) else {}
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
                                     "request_type": item.get("request_type") or "add"},
                         "created_at": int(item.get("submitted_at") or now), "reviewed_at": item.get("reviewed_at")})
    _upsert(connection, tracking_requests, requests, [tracking_requests.c.id])
    return {"favorites": len(favorite_rows), "tracked_ups": len(tracked_rows),
            "tracking_requests": len(requests), "runtime_settings": len(runtime_settings)}


def _count(connection, table) -> int:
    return connection.execute(select(func.count()).select_from(table)).scalar_one()


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
    try:
        with engine.begin() as connection:
            _require_migrated_empty_target(connection, allow_nonempty)
            business_counts = _import_business(connection, business_source)
            auth_counts = _import_auth(connection, auth_source)
            state_counts = _import_json_state(connection, dashboard, tracked, now)
            connection.execute(insert(data_import_records).values(
                id=str(uuid.uuid4()), source_fingerprint=_fingerprint(paths), status="completed", report={}, created_at=now,
            ))
        with engine.begin() as connection:
            video_keys = {row[0] for row in business_source.execute("SELECT bvid FROM videos")} if _rows(business_source, "videos") else set()
            target_keys = set(connection.execute(select(videos.c.bvid)).scalars())
            latest_source = business_source.execute("SELECT MAX(ts) FROM video_obs").fetchone()[0] if _rows(business_source, "video_obs") else None
            latest_target = connection.execute(select(func.max(video_observations.c.ts))).scalar_one()
            dashboard_payload = dashboard.get("dashboard") if isinstance(dashboard.get("dashboard"), dict) else dashboard
            source_settings = dashboard.get("runtime_settings") if isinstance(dashboard.get("runtime_settings"), dict) else {}
            target_dashboard = connection.execute(select(dashboard_state.c.payload).where(
                dashboard_state.c.name == "current",
            )).scalar_one_or_none()
            target_settings = dict(connection.execute(select(
                dashboard_state.c.name, dashboard_state.c.payload,
            ).where(dashboard_state.c.name.in_(tuple(source_settings)))).all()) if source_settings else {}
            report = {
                "valid": False,
                "entities": {
                    "videos": {"source_count": business_counts["videos"], "target_count": _count(connection, videos), "keys_match": video_keys == target_keys},
                    "video_observations": {"source_count": business_counts["video_observations"], "target_count": _count(connection, video_observations)},
                    "ups": {"source_count": business_counts["ups"], "target_count": _count(connection, ups)},
                    "up_observations": {"source_count": business_counts["up_observations"], "target_count": _count(connection, up_observations)},
                    "admins": {"source_count": auth_counts["admins"], "target_count": _count(connection, admin_accounts)},
                },
                "latest_observation_ts": {"source": latest_source, "target": latest_target},
                "sessions": {"source_count": auth_counts["sessions"], "target_count": _count(connection, browser_sessions)},
                "credential_handoffs": {"source_count": auth_counts["credential_handoffs"], "target_count": _count(connection, collector_credential_handoffs)},
                "favorites": {"source_count": state_counts["favorites"], "target_count": _count(connection, favorites)},
                "tracked_ups": {"source_count": state_counts["tracked_ups"], "target_count": _count(connection, tracked_ups)},
                "tracking_requests": {"source_count": state_counts["tracking_requests"], "target_count": _count(connection, tracking_requests)},
                "dashboard_state": {"source_present": True, "target_present": target_dashboard is not None,
                                    "matches": target_dashboard == dashboard_payload},
                "runtime_settings": {"source_count": len(source_settings),
                                     "target_count": len(target_settings),
                                     "matches": target_settings == source_settings},
            }
            report["valid"] = (
                report["entities"]["videos"]["source_count"] == report["entities"]["videos"]["target_count"]
                and report["entities"]["videos"]["keys_match"]
                and report["entities"]["video_observations"]["source_count"] == report["entities"]["video_observations"]["target_count"]
                and report["entities"]["admins"]["source_count"] == report["entities"]["admins"]["target_count"]
                and report["sessions"]["source_count"] == report["sessions"]["target_count"]
                and report["credential_handoffs"]["source_count"] == report["credential_handoffs"]["target_count"]
                and report["favorites"]["source_count"] == report["favorites"]["target_count"]
                and report["tracked_ups"]["source_count"] == report["tracked_ups"]["target_count"]
                and report["latest_observation_ts"]["source"] == report["latest_observation_ts"]["target"]
                and report["dashboard_state"]["target_present"]
                and report["dashboard_state"]["matches"]
                and report["runtime_settings"]["matches"]
            )
            connection.execute(data_import_records.update().where(data_import_records.c.source_fingerprint == _fingerprint(paths)).values(report=report))
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
