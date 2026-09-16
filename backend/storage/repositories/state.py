"""PostgreSQL persistence for mutable dashboard state and favorites."""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from storage.models import dashboard_state, favorites, tracked_up_settings, tracked_ups, tracking_requests, worker_heartbeats


class StateRepository:
    def __init__(self, session_factory):
        self._sessions = session_factory

    @classmethod
    def from_url(cls, url: str) -> "StateRepository":
        engine = create_engine(url, pool_pre_ping=True)
        return cls(sessionmaker(bind=engine, expire_on_commit=False))

    def save_dashboard(self, payload: dict, now: int) -> None:
        with self._sessions.begin() as session:
            session.execute(insert(dashboard_state).values(
                name="current", payload=payload, version=1, updated_at=now,
            ).on_conflict_do_update(
                index_elements=[dashboard_state.c.name],
                set_={"payload": payload, "version": dashboard_state.c.version + 1,
                      "updated_at": now},
            ))

    def load_dashboard(self) -> dict | None:
        with self._sessions() as session:
            row = session.execute(select(dashboard_state.c.payload).where(
                dashboard_state.c.name == "current",
            )).mappings().first()
            return row["payload"] if row else None

    def update_dashboard(self, mutator, now: int, initial: dict | None = None) -> dict:
        """Apply one current-state mutation while holding its PostgreSQL row lock."""
        with self._sessions.begin() as session:
            row = session.execute(select(dashboard_state.c.payload).where(
                dashboard_state.c.name == "current",
            ).with_for_update()).mappings().first()
            payload = dict(row["payload"]) if row else dict(initial or {})
            mutator(payload)
            if row is None:
                session.execute(insert(dashboard_state).values(
                    name="current", payload=payload, version=1, updated_at=now,
                ))
            else:
                session.execute(dashboard_state.update().where(
                    dashboard_state.c.name == "current",
                ).values(payload=payload, version=dashboard_state.c.version + 1, updated_at=now))
            return payload

    def add_favorite(self, item_type: str, item: dict, owner: str | None, now: int) -> dict:
        favorite_id = f"{item_type}_{uuid.uuid4().hex}"
        value = dict(item)
        value.update({"id": favorite_id, "type": item_type, "owner": owner,
                      "saved_at": now, "tags": item.get("tags", []), "notes": item.get("notes", "")})
        with self._sessions.begin() as session:
            session.execute(insert(favorites).values(
                id=favorite_id, owner=owner or "", item_type=item_type, item=value,
                tags=value["tags"], notes=value["notes"], saved_at=now,
            ))
        return value

    def get_favorites(self, owner: str | None, item_type: str | None = None,
                      tag: str | None = None) -> list[dict]:
        if owner is None:
            return []
        statement = select(favorites.c.item).where(favorites.c.owner == owner)
        if item_type:
            statement = statement.where(favorites.c.item_type == item_type)
        with self._sessions() as session:
            rows = [row["item"] for row in session.execute(statement).mappings()]
        return [row for row in rows if tag is None or tag in row.get("tags", [])]

    def update_favorite(self, favorite_id: str, tags: list | None, notes: str | None,
                        owner: str | None) -> dict | None:
        if owner is None:
            return None
        with self._sessions.begin() as session:
            row = session.execute(select(favorites.c.item).where(
                favorites.c.id == favorite_id, favorites.c.owner == owner,
            ).with_for_update()).mappings().first()
            if row is None:
                return None
            item = dict(row["item"])
            if tags is not None:
                item["tags"] = tags
            if notes is not None:
                item["notes"] = notes
            session.execute(favorites.update().where(favorites.c.id == favorite_id).values(
                item=item, tags=item.get("tags", []), notes=item.get("notes", ""),
            ))
            return item

    def remove_favorite(self, favorite_id: str, owner: str | None) -> bool:
        if owner is None:
            return False
        with self._sessions.begin() as session:
            return session.execute(favorites.delete().where(
                favorites.c.id == favorite_id, favorites.c.owner == owner,
            )).rowcount > 0

    def create_tracking_request(self, mid: int, visitor_id: str, snapshot: dict,
                                reason: str, now: int) -> str:
        request_id = f"req_{uuid.uuid4().hex}"
        with self._sessions.begin() as session:
            session.execute(select(func.pg_advisory_xact_lock(mid)))
            pending = session.execute(select(tracking_requests.c.id).where(
                tracking_requests.c.mid == mid,
                tracking_requests.c.status == "pending",
            )).scalar_one_or_none()
            if pending is not None:
                raise ValueError("DUPLICATE")
            session.execute(insert(tracking_requests).values(
                id=request_id, mid=mid, visitor_id=visitor_id, status="pending",
                payload={"up": snapshot, "reason": reason, "request_type": "add"},
                created_at=now,
            ))
        return request_id

    def withdraw_tracking_request(self, request_id: str, visitor_id: str, now: int) -> str | None:
        with self._sessions.begin() as session:
            request = session.execute(select(tracking_requests.c.visitor_id).where(
                tracking_requests.c.id == request_id,
                tracking_requests.c.status == "pending",
            ).with_for_update()).mappings().first()
            if request is None:
                return "NOT_FOUND"
            if request["visitor_id"] != visitor_id:
                return "NOT_OWNER"
            session.execute(tracking_requests.update().where(
                tracking_requests.c.id == request_id,
            ).values(status="withdrawn", reviewed_at=now))
            return None

    def tracking_requests_for(self, visitor_id: str | None = None) -> list[dict]:
        statement = select(tracking_requests).order_by(tracking_requests.c.created_at.desc())
        if visitor_id is not None:
            statement = statement.where(tracking_requests.c.visitor_id == visitor_id)
        with self._sessions() as session:
            rows = session.execute(statement).mappings()
            return [{
                "id": row["id"], "mid": row["mid"],
                "request_type": row["payload"].get("request_type", "add"),
                "up": row["payload"].get("up", {}), "reason": row["payload"].get("reason", ""),
                "visitor_id": row["visitor_id"], "submitted_at": row["created_at"],
                "status": row["status"], "reviewed_at": row["reviewed_at"],
            } for row in rows]

    def record_worker_heartbeat(self, worker_id: str, heartbeat_at: int, details: dict) -> None:
        with self._sessions.begin() as session:
            session.execute(insert(worker_heartbeats).values(
                worker_id=worker_id, heartbeat_at=heartbeat_at, details=details,
            ).on_conflict_do_update(
                index_elements=[worker_heartbeats.c.worker_id],
                set_={"heartbeat_at": heartbeat_at, "details": details},
            ))

    def worker_heartbeat(self, worker_id: str) -> int | None:
        with self._sessions() as session:
            return session.execute(select(worker_heartbeats.c.heartbeat_at).where(
                worker_heartbeats.c.worker_id == worker_id,
            )).scalar_one_or_none()

    def review_tracking_request(self, request_id: str, action: str, now: int) -> dict:
        if action not in {"approve", "reject"}:
            raise ValueError("invalid tracking request action")
        with self._sessions.begin() as session:
            request = session.execute(select(tracking_requests).where(
                tracking_requests.c.id == request_id,
                tracking_requests.c.status == "pending",
            ).with_for_update()).mappings().first()
            if request is None:
                raise LookupError("tracking request not found")
            if action == "reject":
                session.execute(tracking_requests.update().where(
                    tracking_requests.c.id == request_id,
                ).values(status="rejected", reviewed_at=now))
                return {"added_to_pool": False}
            existing = session.execute(select(tracked_ups.c.mid).where(
                tracked_ups.c.mid == request["mid"],
            ).with_for_update()).scalar_one_or_none()
            session.execute(tracking_requests.update().where(
                tracking_requests.c.id == request_id,
            ).values(status="approved", reviewed_at=now))
            session.execute(insert(tracked_ups).values(
                mid=request["mid"], payload=request["payload"]["up"], enabled=True, updated_at=now,
            ).on_conflict_do_update(
                index_elements=[tracked_ups.c.mid],
                set_={"payload": request["payload"]["up"], "enabled": True, "updated_at": now},
            ))
            return {"added_to_pool": existing is None}

    def tracked_mids(self) -> list[int]:
        with self._sessions() as session:
            return list(session.execute(select(tracked_ups.c.mid).where(
                tracked_ups.c.enabled.is_(True),
            ).order_by(tracked_ups.c.mid)).scalars())

    def save_tracked_list(self, ups: list[dict], updated_at: int, config: dict | None = None) -> None:
        mids = {int(up["mid"]) for up in ups}
        with self._sessions.begin() as session:
            if mids:
                session.execute(tracked_ups.delete().where(
                    tracked_ups.c.mid.not_in(mids),
                ))
            else:
                session.execute(tracked_ups.delete())
            for up in ups:
                session.execute(insert(tracked_ups).values(
                    mid=int(up["mid"]), payload=up, enabled=up.get("enabled", True), updated_at=updated_at,
                ).on_conflict_do_update(
                    index_elements=[tracked_ups.c.mid],
                    set_={"payload": up, "enabled": up.get("enabled", True), "updated_at": updated_at},
                ))
            session.execute(insert(tracked_up_settings).values(
                name="tracked_list", payload={"config": config or {}}, updated_at=updated_at,
            ).on_conflict_do_update(
                index_elements=[tracked_up_settings.c.name],
                set_={"payload": {"config": config or {}}, "updated_at": updated_at},
            ))

    def load_tracked_list(self) -> dict | None:
        with self._sessions() as session:
            setting = session.execute(select(tracked_up_settings.c.payload,
                                             tracked_up_settings.c.updated_at).where(
                tracked_up_settings.c.name == "tracked_list",
            )).mappings().first()
            rows = session.execute(select(tracked_ups.c.payload).order_by(tracked_ups.c.mid)).mappings()
            ups = [row["payload"] for row in rows]
            if setting is None and not ups:
                return None
            return {"ups": ups, "config": (setting or {"payload": {}})["payload"].get("config", {}),
                    "updated_at": (setting or {"updated_at": 0})["updated_at"]}

    def save_tracked_config(self, config: dict, updated_at: int) -> None:
        with self._sessions.begin() as session:
            session.execute(insert(tracked_up_settings).values(
                name="tracked_list", payload={"config": config}, updated_at=updated_at,
            ).on_conflict_do_update(
                index_elements=[tracked_up_settings.c.name],
                set_={"payload": {"config": config}, "updated_at": updated_at},
            ))
