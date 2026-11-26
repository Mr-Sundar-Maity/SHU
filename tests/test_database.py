import sqlite3
from contextlib import closing

import pytest

from database.database import SCHEMA_VERSION, Database, _MIGRATIONS, _SCHEMA


def test_database_initializes_schema_and_passes_integrity_check(tmp_path):
    database = Database(tmp_path / "memory" / "shu.db")
    database.initialize()

    assert database.integrity_check() == "ok"
    with database.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "memories",
            "messages",
            "tasks",
            "reminders",
            "audit_logs",
            "communication_drafts",
            "contacts",
        } <= tables
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_database_backup_is_consistent_and_refuses_overwrite(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    backup = database.backup_to(tmp_path / "backups" / "shu.db")

    assert backup.exists()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with pytest.raises(FileExistsError):
        database.backup_to(backup)


def test_database_backup_cannot_replace_a_destination_created_during_staging(tmp_path, monkeypatch):
    from database import database as database_module

    database = Database(tmp_path / "shu.db")
    database.initialize()
    folder = tmp_path / "backups"
    target = folder / "shu.db"
    original_mkstemp = database_module.tempfile.mkstemp

    def create_stage_and_destination(**kwargs):
        result = original_mkstemp(**kwargs)
        target.write_bytes(b"A different backup appeared")
        return result

    monkeypatch.setattr(database_module.tempfile, "mkstemp", create_stage_and_destination)
    with pytest.raises(FileExistsError):
        database.backup_to(target)

    assert target.read_bytes() == b"A different backup appeared"
    assert list(folder.iterdir()) == [target]
    assert database.integrity_check() == "ok"


def test_database_backup_leaves_no_published_copy_of_invalid_database(tmp_path):
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"Not an SQLite database")
    target = tmp_path / "backups" / "shu.db"

    with pytest.raises(sqlite3.DatabaseError):
        Database(path).backup_to(target)

    assert list(target.parent.iterdir()) == []
    assert path.read_bytes() == b"Not an SQLite database"


def test_backup_rotation_keeps_newest_shu_files_and_preserves_unrelated_files(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    names = [
        "shu-20260101T000000000001Z.db",
        "shu-20260102T000000000001Z.db",
        "shu-20260103T000000000001Z.db",
        "shu-custom.db",
        "unrelated.db",
    ]
    for name in names:
        (folder / name).write_text("backup", encoding="utf-8")

    removed = Database.prune_timestamped_backups(folder, keep=2)

    assert [path.name for path in removed] == ["shu-20260101T000000000001Z.db"]
    assert (folder / "shu-20260102T000000000001Z.db").exists()
    assert (folder / "shu-20260103T000000000001Z.db").exists()
    assert (folder / "shu-custom.db").exists()
    assert (folder / "unrelated.db").exists()
    with pytest.raises(ValueError, match="at least 1"):
        Database.prune_timestamped_backups(folder, keep=0)


def test_database_migration_makes_backup_before_advancing_version(tmp_path):
    path = tmp_path / "shu.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA)
        connection.execute("PRAGMA user_version = 1")
    database = Database(path)
    database.initialize()

    assert database.integrity_check() == "ok"
    assert path.with_name("shu.db.v1.bak").exists()
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='communication_drafts'"
        ).fetchone() is not None
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(communication_drafts)")
        }
        assert "attachments_json" in columns
        task_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tasks)")
        }
        assert {"runner_pid", "inflight_step"} <= task_columns


def test_database_restore_preserves_current_data_and_restores_backup(tmp_path):
    live = Database(tmp_path / "memory" / "shu.db")
    live.initialize()
    with live.connect() as connection:
        with connection:
            connection.execute(
                "INSERT INTO user_preferences VALUES(?,?,?,?,?)",
                ("pref-1", "theme", "dark", "user", "2026-01-01T00:00:00+00:00"),
            )
    backup = live.backup_to(tmp_path / "backups" / "known-good.db")

    with live.connect() as connection:
        with connection:
            connection.execute("UPDATE user_preferences SET value='light' WHERE key='theme'")

    restored, preserved = live.restore_from(backup)

    assert restored == live.path
    assert preserved is not None and preserved.is_file()
    with live.connect() as connection:
        assert connection.execute(
            "SELECT value FROM user_preferences WHERE key='theme'"
        ).fetchone()[0] == "dark"
    with sqlite3.connect(preserved) as connection:
        assert connection.execute(
            "SELECT value FROM user_preferences WHERE key='theme'"
        ).fetchone()[0] == "light"


def test_database_backup_restores_into_a_fresh_destination(tmp_path, monkeypatch):
    source = Database(tmp_path / "source" / "shu.db")
    source.initialize()
    with source.connect() as connection:
        with connection:
            connection.execute(
                "INSERT INTO user_preferences VALUES(?,?,?,?,?)",
                ("pref-restore", "language", "Bengali", "owner", "2026-01-01T00:00:00+00:00"),
            )
    backup = source.backup_to(tmp_path / "backup" / "shu-known-good.db")
    fresh_destination = Database(tmp_path / "clean-profile" / "memory" / "shu.db")
    opens = []
    connect = sqlite3.connect

    def track_restore_source(path, *args, **kwargs):
        if path == backup.as_uri() + "?mode=ro":
            opens.append(path)
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", track_restore_source)

    restored_path, preserved_live_copy = fresh_destination.restore_from(backup)

    assert len(opens) == 1
    assert restored_path == fresh_destination.path
    assert preserved_live_copy is None
    assert fresh_destination.integrity_check() == "ok"
    with fresh_destination.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute(
            "SELECT value FROM user_preferences WHERE key='language'"
        ).fetchone()[0] == "Bengali"


def test_database_restore_rejects_unversioned_sqlite_file(tmp_path):
    live = Database(tmp_path / "shu.db")
    live.initialize()
    invalid = tmp_path / "not-shu.db"
    with sqlite3.connect(invalid) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")

    with pytest.raises(ValueError, match="valid versioned SHU backup"):
        live.restore_from(invalid)


def test_restore_rejects_missing_shu_columns_before_preserving_or_replacing_live(tmp_path):
    live = Database(tmp_path / "memory" / "shu.db")
    live.initialize()
    original = live.path.read_bytes()
    incomplete = live.backup_to(tmp_path / "incomplete.db")
    with closing(sqlite3.connect(incomplete)) as connection, connection:
        connection.execute("ALTER TABLE reminders RENAME COLUMN text TO not_the_shu_column")

    with pytest.raises(ValueError, match="valid versioned SHU backup"):
        live.restore_from(incomplete)

    assert live.path.read_bytes() == original
    assert not (live.path.parent / "backups").exists()
    assert not live.path.with_name("shu.db.restore.tmp").exists()


@pytest.mark.parametrize("suffix", ("-wal", "-shm", "-journal"))
def test_restore_leaves_a_destination_with_a_sqlite_journal_untouched(tmp_path, suffix):
    live = Database(tmp_path / "memory" / "shu.db")
    live.initialize()
    original = live.path.read_bytes()
    backup = live.backup_to(tmp_path / "good.db")
    sidecar = live.path.with_name(live.path.name + suffix)
    sidecar.write_bytes(b"Existing journal fixture")

    with pytest.raises(ValueError, match="Close other SHU sessions"):
        live.restore_from(backup)

    assert live.path.read_bytes() == original
    assert sidecar.read_bytes() == b"Existing journal fixture"
    assert not (live.path.parent / "backups").exists()
    assert not live.path.with_name("shu.db.restore.tmp").exists()


def test_restore_refuses_to_overwrite_an_existing_staging_file(tmp_path):
    live = Database(tmp_path / "memory" / "shu.db")
    live.initialize()
    original = live.path.read_bytes()
    backup = live.backup_to(tmp_path / "good.db")
    occupied = live.path.with_name("shu.db.restore.tmp")
    occupied.write_bytes(b"Another restore or an interrupted attempt")

    with pytest.raises(FileExistsError, match="Inspect it before retrying"):
        live.restore_from(backup)

    assert occupied.read_bytes() == b"Another restore or an interrupted attempt"
    assert live.path.read_bytes() == original
    assert not (live.path.parent / "backups").exists()


def test_restore_migrates_a_v2_backup_before_replacing_live_database(tmp_path):
    live = Database(tmp_path / "memory" / "shu.db")
    live.initialize()
    older = tmp_path / "v2-backup.db"
    with sqlite3.connect(older) as connection:
        connection.executescript(_SCHEMA)
        for statement in _MIGRATIONS[2]:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=2")
    with closing(sqlite3.connect(live.path)) as connection, connection:
        connection.execute(
            "INSERT INTO user_preferences VALUES(?,?,?,?,?)",
            ("pref-live", "keep", "live", "user", "2026-01-01T00:00:00+00:00"),
        )

    live.restore_from(older)

    assert not list(live.path.parent.glob("*.restore.tmp*"))
    with closing(sqlite3.connect(older)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    with live.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(communication_drafts)")
        }
        assert "attachments_json" in columns
        assert connection.execute("SELECT COUNT(*) FROM user_preferences").fetchone()[0] == 0


def test_v4_database_migration_backs_up_and_adds_local_contacts(tmp_path):
    path = tmp_path / "shu.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA)
        for version in range(2, 5):
            for statement in _MIGRATIONS[version]:
                connection.execute(statement)
        connection.execute("PRAGMA user_version=4")

    database = Database(path)
    database.initialize()

    assert database.integrity_check() == "ok"
    assert path.with_name("shu.db.v4.bak").exists()
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert {
            row[1] for row in connection.execute("PRAGMA table_info(contacts)")
        } == {
            "contact_id",
            "display_name",
            "normalized_name",
            "phone_e164",
            "created_at",
            "updated_at",
        }
