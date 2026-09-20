"""PostgreSQL adapters for dashboard state and favorites."""

import time
from datetime import datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8))
_state_repository = None


def configure_state_repository(repository):
    """Install the process-specific PostgreSQL state repository."""
    global _state_repository
    _state_repository = repository


def _require_state_repository():
    if _state_repository is None:
        raise RuntimeError("PostgreSQL state repository is not configured")
    return _state_repository


def _initial_data():
    return {
        "hot_memes": [],
        "hot_songs": [],
        "hot_videos": [],
        "danmaku_words": [],
        "comments_gold": [],
        "favorites": [],
        "last_updated": None,
    }


def init_db():
    """Ensure the current dashboard row exists; this never creates schema."""
    repository = _require_state_repository()
    if repository.load_dashboard() is None:
        repository.save_dashboard(_initial_data(), int(time.time()))


def load_data():
    payload, _ = load_data_snapshot()
    return payload


def load_data_snapshot():
    """Return a dashboard payload and its PostgreSQL version from one read."""
    payload, version = _require_state_repository().load_dashboard_snapshot()
    return (payload or _initial_data()), version


def get_data_version():
    return _require_state_repository().dashboard_version()


def save_data(data):
    data["last_updated"] = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    _require_state_repository().save_dashboard(data, int(time.time()))


def update_data(mutator):
    """Apply a read-modify-write under the repository's dashboard row lock."""
    def postgres_mutator(data):
        mutator(data)
        data["last_updated"] = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")

    return _require_state_repository().update_dashboard(
        postgres_mutator, int(time.time()), _initial_data(),
    )


def add_favorite(item_type, item, owner=None):
    return _require_state_repository().add_favorite(
        item_type, item, owner, int(time.time()),
    )


def remove_favorite(item_id, owner=None):
    return _require_state_repository().remove_favorite(item_id, owner)


def update_favorite(item_id, tags=None, notes=None, owner=None):
    return _require_state_repository().update_favorite(item_id, tags, notes, owner)


def get_favorites(item_type=None, tag=None, owner=None):
    return _require_state_repository().get_favorites(owner, item_type, tag)


def migrate_legacy_favorites(mid):
    """Claim unowned/imported-admin favorites in PostgreSQL."""
    return _require_state_repository().claim_legacy_favorites(str(mid))
