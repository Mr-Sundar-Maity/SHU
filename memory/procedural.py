"""User-approved reusable workflow storage."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from database.database import Database
from memory.memory_validator import validate_memory


class ProceduralMemory:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add(self, name: str, steps: list[dict], *, approved: bool = False) -> str:
        if not approved:
            raise PermissionError("Saving a workflow requires explicit approval")
        clean_name, serialized_steps = self._validated(name, steps)
        procedure_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    "INSERT INTO procedural_memories(procedure_id,name,steps_json,approval_status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (procedure_id, clean_name, serialized_steps, "approved", now, now),
                )
                self._audit(connection, procedure_id, "workflow.create", "approved")
        return procedure_id

    def list_all(self) -> list[sqlite3.Row]:
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM procedural_memories ORDER BY name,created_at"
            ).fetchall()

    def get(self, procedure_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM procedural_memories WHERE procedure_id=?", (procedure_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Workflow not found")
        try:
            steps = json.loads(row["steps_json"])
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("Saved workflow is invalid") from error
        if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
            raise ValueError("Saved workflow must contain a list of object steps")
        return {
            "procedure_id": row["procedure_id"],
            "name": row["name"],
            "steps": steps,
            "approval_status": row["approval_status"],
            "version": int(row["version"]),
        }

    def update(self, procedure_id: str, name: str, steps: list[dict], *, approved: bool = False) -> None:
        if not approved:
            raise PermissionError("Editing a workflow requires explicit approval")
        clean_name, serialized_steps = self._validated(name, steps)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE procedural_memories SET name=?,steps_json=?,version=version+1,"
                    "approval_status='pending',updated_at=? WHERE procedure_id=? "
                    "AND approval_status IN ('approved','pending')",
                    (clean_name, serialized_steps, now, procedure_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Only an active workflow can be edited")
                self._audit(connection, procedure_id, "workflow.update", "pending_reapproval")

    def approve(self, procedure_id: str, *, approved: bool = False) -> None:
        if not approved:
            raise PermissionError("Approving a workflow requires explicit approval")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE procedural_memories SET approval_status='approved',updated_at=? "
                    "WHERE procedure_id=? AND approval_status='pending'",
                    (now, procedure_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Only a pending workflow can be approved")
                self._audit(connection, procedure_id, "workflow.approve", "approved")

    def revoke(self, procedure_id: str, *, approved: bool = False) -> None:
        if not approved:
            raise PermissionError("Revoking a workflow requires explicit approval")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE procedural_memories SET approval_status='revoked',updated_at=? "
                    "WHERE procedure_id=? AND approval_status IN ('approved','pending')",
                    (now, procedure_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Only an active workflow can be revoked")
                self._audit(connection, procedure_id, "workflow.revoke", "revoked")

    def list_approved(self) -> list[sqlite3.Row]:
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM procedural_memories WHERE approval_status='approved' ORDER BY name"
            ).fetchall()

    def get_approved(self, procedure_id: str) -> tuple[str, list[dict]]:
        """Load and validate an explicitly approved workflow record."""
        record = self.get(procedure_id)
        if record["approval_status"] != "approved":
            raise KeyError("Approved workflow not found")
        steps = record["steps"]
        if not isinstance(steps, list) or not steps or not all(
            isinstance(step, dict) for step in steps
        ):
            raise ValueError("Saved workflow must contain object steps")
        return record["name"], steps

    @staticmethod
    def _validated(name: str, steps: list[dict]) -> tuple[str, str]:
        if not isinstance(name, str) or not name.strip() or not isinstance(steps, list) or not steps:
            raise ValueError("A workflow needs a name and at least one step")
        if len(steps) > 100 or not all(isinstance(step, dict) for step in steps):
            raise ValueError("A workflow must have at most 100 object steps")
        serialized_steps = json.dumps(steps, ensure_ascii=False)
        validate_memory(
            content=name + "\n" + serialized_steps,
            memory_type="procedural",
            sensitivity="normal",
            confidence=0.5,
            approved=True,
        )
        return name.strip(), serialized_steps

    @staticmethod
    def _audit(connection: sqlite3.Connection, procedure_id: str, action: str, result: str) -> None:
        connection.execute(
            "INSERT INTO audit_logs(log_id,actor,tool,action_summary,risk,approval,result,timestamp) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                "procedural_memory",
                "workflow_control",
                json.dumps({"procedure_id": procedure_id, "action": action}),
                "L2",
                "approved",
                result,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
