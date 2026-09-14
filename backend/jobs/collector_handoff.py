"""Worker-owned durable handoff from authenticated API requests to collector Cookie storage."""

import json
import threading

from collectors.bilibili_auth import logout, save_cookie
from logger import get_logger
from storage.auth_store import complete_collector_action, get_pending_collector_action


logger = get_logger(__name__)
_worker_lock = threading.Lock()
_worker_started = False


def process_pending_collector_action():
    """Process one oldest handoff and acknowledge only after its idempotent file operation."""
    pending = get_pending_collector_action()
    if pending is None:
        return False

    if pending["action"] == "replace":
        cookies = json.loads(pending["payload"])
        save_cookie(cookies)
    elif pending["action"] == "delete":
        logout()
    else:  # Schema CHECK prevents this, but fail closed on a corrupt database.
        raise ValueError(f"unsupported collector handoff action: {pending['action']}")

    complete_collector_action(pending["id"])
    return True


def _run_collector_handoff_worker(stop_event, poll_seconds):
    while not stop_event.is_set():
        try:
            processed = process_pending_collector_action()
        except Exception:
            logger.exception("采集凭证交接处理失败，将保留记录并重试")
            processed = False
        if not processed:
            stop_event.wait(poll_seconds)


def ensure_collector_handoff_worker(stop_event=None, poll_seconds=1.0):
    """Start the single in-process consumer used by the dedicated Worker container."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return None
        _worker_started = True
    stop_event = stop_event or threading.Event()
    thread = threading.Thread(
        target=_run_collector_handoff_worker,
        args=(stop_event, poll_seconds),
        name="collector-credential-handoff",
        daemon=True,
    )
    thread.start()
    return thread
