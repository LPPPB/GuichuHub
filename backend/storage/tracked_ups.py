"""PostgreSQL adapters for tracked UPs and tracking requests."""

import time

DEFAULT_CONFIG = {}
REQUESTS_PENDING_LIMIT = 50
REQUESTS_PROCESSED_KEEP = 100
REQUESTS_DAILY_LIMIT = 3
TRACK_POOL_LIMIT = 300

_state_repository = None


def configure_state_repository(repository):
    """Install the process-specific PostgreSQL state repository."""
    global _state_repository
    _state_repository = repository


def _require_state_repository():
    if _state_repository is None:
        raise RuntimeError("PostgreSQL state repository is not configured")
    return _state_repository


def load_config():
    tracked = _require_state_repository().load_tracked_list()
    return {**DEFAULT_CONFIG, **(tracked or {}).get("config", {})}


def save_config(config):
    _require_state_repository().save_tracked_config(
        {**DEFAULT_CONFIG, **config}, int(time.time()),
    )


def load_tracked_list():
    tracked = _require_state_repository().load_tracked_list()
    if tracked is None:
        return None
    return {
        "ups": tracked.get("ups", []),
        "config": {**DEFAULT_CONFIG, **tracked.get("config", {})},
        "updated_at": tracked.get("updated_at", 0),
    }


def save_tracked_list(ups, updated_at=None):
    _require_state_repository().save_tracked_list(
        ups, updated_at or int(time.time()),
    )


def has_tracked_list():
    tracked = _require_state_repository().load_tracked_list()
    if tracked and tracked.get("ups"):
        return True
    try:
        from storage.up_obs_reader import get_latest_batch_ts
        return bool(get_latest_batch_ts())
    except Exception:
        return False


def diff_mutual_list(existing_ups, fresh_mutuals):
    """
    Compare the existing roster with the latest mutual-following list.
    Returns added, removed, and unchanged entries, refreshing names and faces.
    """
    existing_mids = {up["mid"] for up in existing_ups}
    fresh_mids = {up["mid"] for up in fresh_mutuals}
    existing_by_mid = {up["mid"]: up for up in existing_ups}
    fresh_by_mid = {up["mid"]: up for up in fresh_mutuals}

    added = [fresh_by_mid[mid] for mid in fresh_mids - existing_mids]
    removed = [existing_by_mid[mid] for mid in existing_mids - fresh_mids]
    unchanged = []
    for mid in existing_mids & fresh_mids:
        up = dict(existing_by_mid[mid])
        up["name"] = fresh_by_mid[mid].get("name", up.get("name", ""))
        up["face"] = fresh_by_mid[mid].get("face", up.get("face", ""))
        unchanged.append(up)
    return {"added": added, "removed": removed, "unchanged": unchanged}


def add_up_request(mid, snapshot, reason, visitor_id, request_type="add"):
    """Create a validated PostgreSQL tracking request.

    Returns (request_dict, None) or (None, error_code).
    """
    if request_type not in ("add", "remove"):
        return None, "INVALID_TYPE"
    now = int(time.time())
    try:
        request_id = _require_state_repository().create_tracking_request(
            int(mid), visitor_id, snapshot or {}, str(reason or ""), now,
            request_type=request_type,
            pending_limit=REQUESTS_PENDING_LIMIT,
            daily_limit=REQUESTS_DAILY_LIMIT,
            pool_limit=TRACK_POOL_LIMIT,
        )
    except (TypeError, ValueError) as exc:
        return None, str(exc)
    return {
        "id": request_id,
        "mid": int(mid),
        "request_type": request_type,
        "up": snapshot or {},
        "reason": str(reason or ""),
        "visitor_id": visitor_id,
        "submitted_at": now,
        "status": "pending",
    }, None


def get_my_up_requests(visitor_id):
    requests = _require_state_repository().tracking_requests_for(visitor_id)
    return {
        "pending": [request for request in requests if request["status"] == "pending"],
        "processed": [request for request in requests if request["status"] != "pending"],
    }


def withdraw_up_request(req_id, visitor_id):
    return _require_state_repository().withdraw_tracking_request(
        req_id, visitor_id, int(time.time()),
    )


def list_all_up_requests():
    requests = _require_state_repository().tracking_requests_for()
    pending = [request for request in requests if request["status"] == "pending"]
    return {
        "pending": pending,
        "processed": [request for request in requests if request["status"] != "pending"][:50],
        "pending_count": len(pending),
    }


def review_up_request(req_id, action, reject_reason=None):
    if action not in ("approve", "reject"):
        return None, "NOT_FOUND"
    try:
        result = _require_state_repository().review_tracking_request(
            req_id, action, int(time.time()), reject_reason=reject_reason or "",
            pool_limit=TRACK_POOL_LIMIT,
        )
    except LookupError:
        return None, "NOT_FOUND"
    except ValueError as exc:
        return None, str(exc)
    return result, None
