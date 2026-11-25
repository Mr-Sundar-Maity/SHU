"""SQLite persistence with an explicit, versioned schema and safe backups."""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('system','user','assistant','tool')),
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    language TEXT
);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_time ON messages(conversation_id, timestamp);
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('short_term','long_term','episodic','semantic','procedural','preference')),
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'normal',
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    approved INTEGER NOT NULL DEFAULT 0 CHECK (approved IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    retention_until TEXT
);
CREATE INDEX IF NOT EXISTS ix_memories_type_approved ON memories(type, approved);
CREATE TABLE IF NOT EXISTS user_preferences (
    preference_id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    approved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodic_memories (
    event_id TEXT PRIMARY KEY,
    event_time TEXT NOT NULL,
    summary TEXT NOT NULL,
    application TEXT,
    outcome TEXT NOT NULL,
    memory_id TEXT REFERENCES memories(memory_id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS procedural_memories (
    procedure_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    approval_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    request TEXT NOT NULL,
    plan_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    checkpoint_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS reminders (
    reminder_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL,
    timezone TEXT NOT NULL,
    recurrence TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    last_notified_at TEXT,
    result TEXT
);
CREATE INDEX IF NOT EXISTS ix_reminders_due ON reminders(status, due_at);
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id TEXT PRIMARY KEY,
    task_id TEXT,
    actor TEXT NOT NULL,
    tool TEXT,
    action_summary TEXT NOT NULL,
    risk TEXT NOT NULL,
    approval TEXT NOT NULL,
    result TEXT NOT NULL,
    error_code TEXT,
    timestamp TEXT NOT NULL
);
"""

_MIGRATIONS = {
    2: (
        """CREATE TABLE IF NOT EXISTS communication_drafts (
            draft_id TEXT PRIMARY KEY,
            channel TEXT NOT NULL CHECK (channel IN ('email','whatsapp')),
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            approved_at TEXT,
            sent_at TEXT,
            external_id TEXT,
            result TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS ix_communication_drafts_status ON communication_drafts(status, created_at)",
    ),
    3: (
        "ALTER TABLE communication_drafts ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'",
    ),
    4: (
        "ALTER TABLE tasks ADD COLUMN runner_pid INTEGER",
        "ALTER TABLE tasks ADD COLUMN inflight_step INTEGER",
    ),
    5: (
        """CREATE TABLE IF NOT EXISTS contacts (
            contact_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            phone_e164 TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_contacts_normalized_name ON contacts(normalized_name)",
    ),
}


class Database:
    """Small SQLite wrapper; initialization is explicit and idempotent."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if not self.path.exists():
            raise FileNotFoundError(
                f"Database is not initialized. Call initialize() first: {self.path}"
            )
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create directories and apply the initial schema without data loss."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            current_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema {current_version} is newer than supported "
                    f"schema {SCHEMA_VERSION}"
                )
            if current_version == 0:
                connection.executescript(_SCHEMA)
                connection.execute("PRAGMA user_version = 1")
                current_version = 1
            while current_version < SCHEMA_VERSION:
                target_version = current_version + 1
                backup_path = self.path.with_name(
                    f"{self.path.name}.v{current_version}.bak"
                )
                connection.commit()
                connection.close()
                if not backup_path.exists():
                    self.backup_to(backup_path)
                connection = sqlite3.connect(self.path, timeout=10)
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")
                for statement in _MIGRATIONS[target_version]:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {target_version}")
                connection.commit()
                current_version = target_version
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def integrity_check(self) -> str:
        with self.connect() as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return str(result)

    def backup_to(self, destination: str | Path, *, overwrite: bool = False) -> Path:
        """Create a consistent SQLite backup; refuse overwrite by default."""
        target = Path(destination).expanduser()
        if target.resolve() == self.path.resolve():
            raise ValueError("Backup destination must differ from the live database")
        if target.exists() and not overwrite:
            raise FileExistsError(f"Backup already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_target = target.with_name(target.name + ".tmp")
        if temp_target.exists():
            raise FileExistsError(f"Temporary backup already exists: {temp_target}")

        try:
            with self.connect() as source:
                backup = sqlite3.connect(temp_target)
                try:
                    source.backup(backup)
                    backup.commit()
                finally:
                    backup.close()
            if target.exists() and overwrite:
                os.replace(temp_target, target)
            else:
                temp_target.rename(target)
        except Exception:
            if temp_target.exists():
                temp_target.unlink()
            raise
        return target

    @staticmethod
    def prune_timestamped_backups(directory: str | Path, *, keep: int = 10) -> list[Path]:
        """Remove old SHU CLI backups while leaving all other files untouched."""
        if keep < 1:
            raise ValueError("keep must be at least 1")
        folder = Path(directory).expanduser()
        if not folder.is_dir():
            return []
        owned_name = re.compile(r"^shu-\d{8}T\d{12}Z\.db$")
        backups = sorted(
            (path for path in folder.iterdir() if path.is_file() and owned_name.fullmatch(path.name)),
            key=lambda path: path.name,
            reverse=True,
        )
        removed: list[Path] = []
        for old_backup in backups[keep:]:
            old_backup.unlink()
            removed.append(old_backup)
        return removed

    def restore_from(self, source: str | Path) -> tuple[Path, Path | None]:
        """Restore a verified SHU backup, migrate it, and preserve live data first."""
        backup = Path(source).expanduser().resolve()
        if not backup.is_file():
            raise FileNotFoundError(f"Restore source does not exist: {backup}")
        if backup == self.path.resolve():
            raise ValueError("Restore source must differ from the live database")

        source_uri = backup.as_uri() + "?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
            integrity = source_connection.execute("PRAGMA integrity_check").fetchone()[0]
            version = source_connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in source_connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        required_tables = {"memories", "messages", "tasks", "reminders", "audit_logs"}
        has_comms = version < 2 or "communication_drafts" in tables
        if (
            integrity != "ok"
            or version < 1
            or version > SCHEMA_VERSION
            or not required_tables <= tables
            or not has_comms
        ):
            raise ValueError("Restore source is not a valid versioned SHU backup")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        current_backup: Path | None = None
        if self.path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            current_backup = self.path.parent / "backups" / f"{self.path.stem}-before-restore-{stamp}.db"
            self.backup_to(current_backup)

        temporary = self.path.with_name(self.path.name + ".restore.tmp")
        if temporary.exists():
            raise FileExistsError(f"Temporary restore file already exists: {temporary}")
        try:
            with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
                with closing(sqlite3.connect(temporary)) as target_connection:
                    source_connection.backup(target_connection)
                    target_connection.commit()
            with closing(sqlite3.connect(temporary)) as verification:
                restored_integrity = verification.execute("PRAGMA integrity_check").fetchone()[0]
                restored_version = verification.execute("PRAGMA user_version").fetchone()[0]
            if restored_version < SCHEMA_VERSION:
                Database(temporary).initialize()
                with closing(sqlite3.connect(temporary)) as verification:
                    restored_integrity = verification.execute("PRAGMA integrity_check").fetchone()[0]
                    restored_version = verification.execute("PRAGMA user_version").fetchone()[0]
            if restored_integrity != "ok" or restored_version != SCHEMA_VERSION:
                raise ValueError("Restored copy failed integrity or version verification")
            os.replace(temporary, self.path)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
        return self.path, current_backup
