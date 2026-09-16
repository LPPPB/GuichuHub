"""PostgreSQL persistence for administrators and browser sessions."""

from __future__ import annotations

import secrets

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from storage.models import admin_accounts, browser_sessions


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
            result = session.execute(insert(admin_accounts).values(**row).on_conflict_do_nothing(
                index_elements=[admin_accounts.c.mid],
            ))
            if result.rowcount == 0:
                return None, "EXISTS"
        return row, None

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
