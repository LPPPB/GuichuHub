"""PostgreSQL adapter for administrators, browser sessions, and credential handoffs.

Cookie-bearing session data is consumed only by the server-side authentication
flow and is never included in the public session result.
"""

import time

SESSION_TTL = 30 * 24 * 3600

_auth_repository = None


def configure_auth_repository(repository):
    """Install the process-specific PostgreSQL authentication repository."""
    global _auth_repository
    _auth_repository = repository


def _require_auth_repository():
    if _auth_repository is None:
        raise RuntimeError("PostgreSQL auth repository is not configured")
    return _auth_repository


def admin_count():
    return _require_auth_repository().admin_count()


def list_admin_accounts():
    return _require_auth_repository().list_admin_accounts()


def is_admin_mid(mid):
    if mid is None:
        return False
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return False
    return _require_auth_repository().is_admin_mid(mid)


def add_admin_account(mid, name="", face="", added_by=""):
    """Add an administrator. Returns (row, error)."""
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return None, "INVALID"
    if mid <= 0:
        return None, "INVALID"
    return _require_auth_repository().add_admin_account(
        mid, str(name or ""), str(face or ""), str(added_by or ""), int(time.time()),
    )


def remove_admin_account(mid):
    """Remove an administrator, protecting the last remaining account."""
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return False, "NOT_FOUND"
    return _require_auth_repository().remove_admin_account(mid)


def update_admin_profile(mid, name, face):
    """Refresh profile data for an existing administrator."""
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return False
    if not name and not face:
        return False
    return _require_auth_repository().update_admin_profile(
        mid, str(name or ""), str(face or ""),
    )


def create_session(visitor_id, mid, name, face, cookies):
    """Issue a server-side session token; credentials remain in PostgreSQL."""
    return _require_auth_repository().create_session(
        visitor_id, mid, name, face, cookies, int(time.time()),
    )


def get_session(token):
    """Read a session without exposing its stored credentials."""
    if not token or not isinstance(token, str) or len(token) > 128:
        return None
    return _require_auth_repository().get_session(token, int(time.time()))


def delete_session(token):
    """Delete a session; returns whether a row was removed."""
    if not token:
        return False
    return _require_auth_repository().delete_session(token)


def list_recent_logins(limit=10):
    return _require_auth_repository().list_recent_logins(limit)


def purge_expired_sessions():
    return _require_auth_repository().purge_expired_sessions(int(time.time()))


def request_collector_cookie_update(cookies, requested_by):
    """Queue an authenticated credential handoff for the Worker."""
    if not requested_by:
        raise ValueError("collector handoff requires an authenticated requester")
    return _require_auth_repository().request_collector_action(
        "replace", cookies or {}, str(requested_by), int(time.time()),
    )


def request_collector_logout(requested_by):
    """Queue an authenticated collector logout for the Worker."""
    if not requested_by:
        raise ValueError("collector handoff requires an authenticated requester")
    return _require_auth_repository().request_collector_action(
        "delete", {}, str(requested_by), int(time.time()),
    )


def get_pending_collector_action():
    return _require_auth_repository().pending_collector_action()


def complete_collector_action(action_id):
    return _require_auth_repository().complete_collector_action(int(action_id))
