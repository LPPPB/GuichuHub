"""Create transactionally consistent SQLite backups."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def create_backup(source: Path, destination_dir: Path) -> Path:
    """Back up ``source`` through SQLite's online backup API."""
    source = Path(source)
    destination_dir = Path(destination_dir)
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")

    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = destination_dir / f"kichu_backup_{timestamp}.db"

    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
        source_db.backup(backup_db)

    return destination


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a consistent online backup of a SQLite database."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    destination = create_backup(args.source, args.destination)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
