"""Time-stamped event persistence for SHU."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from database.database import Database


class EpisodicMemory:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(
        self,
        summary: str,
        *,
        outcome: str,
        application: str | None = None,
        approved: bool = False,
    ) -> str:
        if not approved:
            raise PermissionError("Recording an episodic memory requires approval")
        if not summary.strip() or not outcome.strip():
            raise ValueError("summary and outcome are required")
        event_id = str(uuid.uuid4())
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    "INSERT INTO episodic_memories(event_id,event_time,summary,application,outcome) VALUES(?,?,?,?,?)",
                    (
                        event_id,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        summary.strip(),
                        application,
                        outcome.strip(),
                    ),
                )
        return event_id
