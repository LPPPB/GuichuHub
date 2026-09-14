import sqlite3

from ops.backup.backup import create_backup


def test_create_backup_contains_committed_wal_rows(tmp_path):
    source = tmp_path / "source.db"
    destination_dir = tmp_path / "backups"

    with sqlite3.connect(source) as source_db:
        source_db.execute("pragma journal_mode=wal")
        source_db.execute("create table entries (id integer primary key, value text)")
        source_db.execute("insert into entries(value) values (?)", ("preserved",))
        source_db.commit()

        destination = create_backup(source, destination_dir)

    assert destination.parent == destination_dir
    assert destination.name.startswith("kichu_backup_")
    assert destination.suffix == ".db"

    with sqlite3.connect(destination) as backup_db:
        assert backup_db.execute("select value from entries").fetchall() == [
            ("preserved",)
        ]
