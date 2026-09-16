"""PostgreSQL persistence for administrators and browser sessions."""

from __future__ import annotations

import secrets
import json

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from storage.models import admin_accounts, browser_sessions, collector_credential_handoffs


SESSION_TTL = 30 * 24 * 3600


class AuthRepository:
    def __init__(self, session_factory):
        self._sessions = session_factory

    @classmethod
    def from_url(cls, url: str) -> "AuthRepository":
        engine = create_engine(url, pool_pre_ping=True)
        return cls(sessionmaker(bind=engine, expire_on_commit=False))

    def create_session(self, visitor_id: str, mid: int | None, name: str, face: str,
                       cookies: dict, now: int) -> str:
        token = secrets.token_hex(24)
        with self._sessions.begin() as session:
            session.execute(browser_sessions.delete().where(
                browser_sessions.c.visitor_id == visitor_id,
            ))
            session.execute(insert(browser_sessions).values(
                token=token, visitor_id=visitor_id, mid=mid, name=name or "", face=face or "",
                cookies=cookies or {}, created_at=now, expires_at=now + SESSION_TTL,
            ))
        return token

    def get_session(self, token: str, now: int) -> dict | None:
        if not token or not isinstance(token, str) or len(token) > 128:
            return None
        with self._sessions.begin() as session:
            row = session.execute(
                select(browser_sessions).where(browser_sessions.c.token == token)
            ).mappings().first()
            if row is None:
                return None
            if row["expires_at"] < now:
                session.execute(browser_sessions.delete().where(browser_sessions.c.token == token))
                return None
            return {key: row[key] for key in (
                "token", "visitor_id", "mid", "name", "face", "created_at", "expires_at",
            )}

    def add_admin_account(self, mid: int, name: str, face: str, added_by: str, now: int):
        if not isinstance(mid, int) or mid <= 0:
            return None, "INVALID"
        row = {"mid": mid, "name": name or "", "face": face or "", "added_at": now,
               "added_by": added_by or ""}
        with self._sessions.begin() as session:
            inserted_mid = session.execute(insert(admin_accounts).values(**row).on_conflict_do_nothing(
                index_elements=[admin_accounts.c.mid],
            ).returning(admin_accounts.c.mid)).scalar_one_or_none()
            if inserted_mid is None:
                return None, "EXISTS"
        return row, None

    def admin_count(self) -> int:
        with self._sessions() as session:
            return session.execute(select(func.count()).select_from(admin_accounts)).scalar_one()

    def list_admin_accounts(self) -> list[dict]:
        with self._sessions() as session:
            return [dict(row) for row in session.execute(
                select(admin_accounts).order_by(admin_accounts.c.added_at)
            ).mappings()]

    def is_admin_mid(self, mid: int | None) -> bool:
        if not isinstance(mid, int):
            return False
        with self._sessions() as session:
            return session.execute(select(admin_accounts.c.mid).where(
                admin_accounts.c.mid == mid,
            )).scalar_one_or_none() is not None

    def update_admin_profile(self, mid: int, name: str, face: str) -> bool:
        if not isinstance(mid, int) or (not name and not face):
            return False
        with self._sessions.begin() as session:
            return session.execute(admin_accounts.update().where(
                admin_accounts.c.mid == mid,
            ).values(name=name or "", face=face or "")).rowcount > 0

    def remove_admin_account(self, mid: int) -> tuple[bool, str | None]:
        with self._sessions.begin() as session:
            present = session.execute(select(admin_accounts.c.mid).where(
                admin_accounts.c.mid == mid,
            )).scalar_one_or_none()
            if present is None:
                return False, "NOT_FOUND"
            count = session.execute(select(func.count()).select_from(admin_accounts)).scalar_one()
            if count <= 1:
                return False, "LAST_ADMIN"
            session.execute(admin_accounts.delete().where(admin_accounts.c.mid == mid))
            return True, None

    def request_collector_action(self, action: str, payload: dict, requested_by: str, now: int) -> int:
        with self._sessions.begin() as session:
            return session.execute(insert(collector_credential_handoffs).values(
                action=action, payload=payload, requested_by=requested_by, requested_at=now,
            ).returning(collector_credential_handoffs.c.id)).scalar_one()

    def pending_collector_action(self) -> dict | None:
        with self._sessions() as session:
            row = session.execute(select(collector_credential_handoffs).order_by(
                collector_credential_handoffs.c.id,
            ).limit(1)).mappings().first()
            if row is None:
                return None
            result = dict(row)
            result["payload"] = json.dumps(result["payload"], ensure_ascii=False)
            return result

    def complete_collector_action(self, action_id: int) -> bool:
        with self._sessions.begin() as session:
            return session.execute(collector_credential_handoffs.delete().where(
                collector_credential_handoffs.c.id == action_id,
            )).rowcount > 0
