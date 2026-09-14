import sqlite3

from ops.backup import backup
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


def test_create_backup_set_preserves_business_and_auth_databases(tmp_path):
    from ops.backup.backup import create_backup_set

    business = tmp_path / "business.db"
    auth = tmp_path / "auth.db"
    destination_dir = tmp_path / "backups"

    for source, value in ((business, "business-row"), (auth, "auth-row")):
        with sqlite3.connect(source) as db:
            db.execute("pragma journal_mode=wal")
            db.execute("create table entries (value text)")
            db.execute("insert into entries values (?)", (value,))
            db.commit()

    backups = create_backup_set(business, auth, destination_dir)

    assert set(backups) == {"business", "auth"}
    assert backups["business"].name.startswith("business_")
    assert backups["auth"].name.startswith("auth_")
    assert backups["business"] != backups["auth"]
    for label, value in (("business", "business-row"), ("auth", "auth-row")):
        with sqlite3.connect(backups[label]) as db:
            assert db.execute("pragma quick_check").fetchone() == ("ok",)
            assert db.execute("select value from entries").fetchall() == [(value,)]


def test_create_backup_opens_live_wal_source_read_only(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    destination_dir = tmp_path / "backups"
    original_connect = backup.sqlite3.connect
    calls = []

    def observed_connect(*args, **kwargs):
        calls.append((args, kwargs))
        return original_connect(*args, **kwargs)

    with sqlite3.connect(source) as writer:
        writer.execute("pragma journal_mode=wal")
        writer.execute("create table entries (value text)")
        writer.execute("insert into entries values (?)", ("online",))
        writer.commit()
        monkeypatch.setattr(backup.sqlite3, "connect", observed_connect)
        destination = backup.create_backup(source, destination_dir)

    source_args, source_kwargs = calls[0]
    assert source_args[0].startswith("file:")
    assert "mode=ro" in source_args[0]
    assert source_kwargs["uri"] is True
    with sqlite3.connect(destination) as database:
        assert database.execute("select value from entries").fetchall() == [("online",)]
