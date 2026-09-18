"""PostgreSQL-backed mutable runtime settings.

Checked-in vocabularies remain immutable release defaults.  API/Worker edits are
stored as named JSONB rows in ``app.dashboard_state`` and never written to the
source checkout.
"""

from __future__ import annotations

from copy import deepcopy
import time


_state_repository = None
RUNTIME_SETTING_CACHE_REFRESH_SECONDS = 1.0


def configure_runtime_settings_repository(repository) -> None:
    global _state_repository
    _state_repository = repository


def load_runtime_setting(name: str, default):
    if _state_repository is None:
        return deepcopy(default)
    value = _state_repository.load_setting(name)
    return deepcopy(default) if value is None else value


def runtime_setting_version(name: str) -> int:
    """Return the PostgreSQL revision, or zero before runtime wiring."""
    if _state_repository is None:
        return 0
    return _state_repository.setting_version(name)


def save_runtime_setting(name: str, payload) -> None:
    if _state_repository is None:
        raise RuntimeError("PostgreSQL state repository is not configured")
    _state_repository.save_setting(name, payload, int(time.time()))
