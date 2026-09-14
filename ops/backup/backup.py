"""Create transactionally consistent SQLite backups."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def create_backup(source: Path, destination_dir: Path, label: str = "kichu_backup") -> Path:
    """Back up ``source`` through SQLite's online backup API."""
    source = Path(source)
    destination_dir = Path(destination_dir)
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")

    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if not label.replace("-", "").replace("_", "").isalnum():
        raise ValueError("backup label must contain only letters, digits, dashes, or underscores")
    destination = destination_dir / f"{label}_{timestamp}.db"

    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
        source_db.backup(backup_db)

    return destination


def create_backup_set(business_source: Path, auth_source: Path, destination_dir: Path):
    """Create and verify distinct consistent snapshots for both production databases."""
    backups = {
        "business": create_backup(business_source, destination_dir, "business"),
        "auth": create_backup(auth_source, destination_dir, "auth"),
    }
    for destination in backups.values():
        with sqlite3.connect(destination) as database:
            if database.execute("pragma quick_check").fetchone() != ("ok",):
                raise RuntimeError(f"SQLite backup verification failed: {destination}")
    return backups


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create and verify consistent backups of both SQLite databases."
    )
    parser.add_argument("--business-source", type=Path, required=True)
    parser.add_argument("--auth-source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    destinations = create_backup_set(
        args.business_source, args.auth_source, args.destination
    )
    for label, destination in destinations.items():
        print(f"{label}={destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
