"""Reviewable, reversible preference and workflow learning."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from database.database import Database
from memory.procedural import ProceduralMemory
from app.security.registry import Confirmation


_CREDENTIAL_TERMS = re.compile(
    r"(?i)\b(password|passwd|passcode|otp|recovery\s+code|private\s+key|"
    r"api\s+key|access\s+token|refresh\s+token|credential|secret)\b"
)


class LearningService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.procedures = ProceduralMemory(database)

    def record_task_feedback(
        self,
        task_id: str,
        rating: str,
        correction: str = "",
        *,
        approved: bool = False,
    ) -> str:
        """Store an approved, local task rating or correction in the audit log."""
        if not approved:
            raise PermissionError("Recording task feedback requires user approval")
        normalized_rating = rating.strip().lower()
        if normalized_rating not in {"helpful", "needs_improvement"}:
            raise ValueError("rating must be helpful or needs_improvement")
        normalized_correction = correction.strip()
        if len(normalized_correction) > 2_000:
            raise ValueError("Task correction cannot exceed 2000 characters")
        if _CREDENTIAL_TERMS.search(normalized_correction):
            raise ValueError("Credential-related task feedback cannot be stored")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        event_id = str(uuid.uuid4())
        with self.database.connect() as connection:
            with connection:
                if connection.execute(
                    "SELECT 1 FROM tasks WHERE task_id=?", (task_id,)
                ).fetchone() is None:
                    raise KeyError("Task not found")
                connection.execute(
                    """INSERT INTO audit_logs
                    (log_id,task_id,actor,tool,action_summary,risk,approval,result,timestamp)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        event_id,
                        task_id,
                        "learning_service",
                        "task_feedback",
                        json.dumps(
                            {
                                "action": "task.feedback",
                                "rating": normalized_rating,
                                "correction": normalized_correction,
                            },
                            ensure_ascii=False,
                        ),
                        "L1",
                        "approved",
                        "captured",
                        now,
                    ),
                )
        return event_id

    def list_task_feedback(self, task_id: str) -> list[dict[str, str]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT log_id,action_summary,timestamp FROM audit_logs
                WHERE task_id=? AND tool='task_feedback' ORDER BY timestamp,log_id""",
                (task_id,),
            ).fetchall()
        result = []
        for row in rows:
            try:
                summary = json.loads(row["action_summary"])
            except json.JSONDecodeError:
                continue
            if not isinstance(summary, dict) or summary.get("action") != "task.feedback":
                continue
            result.append(
                {
                    "feedback_id": row["log_id"],
                    "rating": str(summary.get("rating", "")),
                    "correction": str(summary.get("correction", "")),
                    "timestamp": row["timestamp"],
                }
            )
        return result

    def save_preference(
        self,
        key: str,
        value: str,
        *,
        source: str = "user",
        approved: bool = False,
    ) -> None:
        if not approved:
            raise PermissionError("Learning a preference requires user approval")
        normalized = key.strip().lower()
        if not normalized or _CREDENTIAL_TERMS.search(normalized.replace("_", " ")):
            raise ValueError("Credential-related preferences cannot be stored")
        if not value or len(value) > 2_000:
            raise ValueError("Preference value must contain 1-2000 characters")
        if _CREDENTIAL_TERMS.search(value):
            raise ValueError("Credential-related preference values cannot be stored")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        preference_id = str(uuid.uuid4())
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    """INSERT INTO user_preferences(preference_id,key,value,source,approved_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,source=excluded.source,approved_at=excluded.approved_at""",
                    (preference_id, normalized, value.strip(), source, now),
                )
                connection.execute(
                    """INSERT INTO audit_logs(log_id,actor,action_summary,risk,approval,result,timestamp)
                    VALUES(?,?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()),
                        "learning_service",
                        json.dumps({"action": "preference.save", "key": normalized}),
                        "L2",
                        "approved",
                        "success",
                        now,
                    ),
                )

    def get_preference(self, key: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT value FROM user_preferences WHERE key=?", (key.strip().lower(),)
            ).fetchone()
        return row[0] if row else None

    def list_preferences(self) -> dict[str, str]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT key,value FROM user_preferences ORDER BY key"
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def delete_preference(self, key: str, *, approved: bool = False) -> bool:
        if not approved:
            raise PermissionError("Deleting a preference requires user approval")
        normalized = key.strip().lower()
        with self.database.connect() as connection:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM user_preferences WHERE key=?", (normalized,)
                )
                if cursor.rowcount:
                    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    connection.execute(
                        """INSERT INTO audit_logs(log_id,actor,action_summary,risk,approval,result,timestamp)
                        VALUES(?,?,?,?,?,?,?)""",
                        (
                            str(uuid.uuid4()),
                            "learning_service",
                            json.dumps({"action": "preference.delete", "key": normalized}),
                            "L2",
                            "approved",
                            "success",
                            now,
                        ),
                    )
                return cursor.rowcount > 0

    def save_workflow(self, name: str, steps: list[dict], *, approved: bool = False) -> str:
        return self.procedures.add(name, steps, approved=approved)

    def update_workflow(
        self,
        procedure_id: str,
        name: str,
        steps: list[dict],
        planner,
        *,
        approved: bool = False,
    ) -> None:
        if not approved:
            raise PermissionError("Editing a workflow requires explicit approval")
        validated_steps = planner.validate_steps(steps)
        self.procedures.update(
            procedure_id,
            name,
            validated_steps,
            approved=True,
        )

    def approve_workflow(self, procedure_id: str, planner, *, approved: bool = False) -> None:
        if not approved:
            raise PermissionError("Approving a workflow requires explicit approval")
        record = self.procedures.get(procedure_id)
        if record["approval_status"] != "pending":
            raise ValueError("Only a pending workflow can be approved")
        planner.validate_steps(record["steps"])
        self.procedures.approve(procedure_id, approved=True)

    def revoke_workflow(self, procedure_id: str, *, approved: bool = False) -> None:
        self.procedures.revoke(procedure_id, approved=approved)

    def preview_workflow(self, procedure_id: str, planner) -> dict:
        """Revalidate a stored workflow against the currently registered tools."""
        record = self.procedures.get(procedure_id)
        if record["approval_status"] != "approved":
            raise KeyError("Approved workflow not found")
        return {
            "procedure_id": procedure_id,
            "name": record["name"],
            "steps": planner.validate_steps(record["steps"]),
            "version": record["version"],
        }

    def create_workflow_task(
        self,
        procedure_id: str,
        planner,
        *,
        expected_version: int,
        approved: bool = False,
    ) -> str:
        """Create a replay task only for the approved version the user reviewed."""
        if not approved:
            raise PermissionError("Replaying a workflow requires explicit approval")
        with self.database.connect() as connection:
            with connection:
                # Acquire SQLite's write reservation before reading so another
                # connection cannot edit or revoke the reviewed version between
                # this check and the task insert.
                connection.execute("BEGIN IMMEDIATE")
                record = connection.execute(
                    "SELECT name,steps_json,version,approval_status "
                    "FROM procedural_memories WHERE procedure_id=?",
                    (procedure_id,),
                ).fetchone()
                if record is None or record["approval_status"] != "approved":
                    raise KeyError("Approved workflow not found")
                if int(record["version"]) != expected_version:
                    raise ValueError(
                        "Workflow changed since review; review it again before replay"
                    )
                try:
                    steps = json.loads(record["steps_json"])
                except (TypeError, json.JSONDecodeError) as error:
                    raise ValueError("Saved workflow is invalid") from error
                if not isinstance(steps, list) or not all(
                    isinstance(step, dict) for step in steps
                ):
                    raise ValueError("Saved workflow must contain a list of object steps")
                validated_steps = planner.validate_steps(steps)
                return planner.create(
                    f"Approved workflow: {record['name']}",
                    validated_steps,
                    connection=connection,
                )

    def run_workflow(
        self,
        procedure_id: str,
        planner,
        executor,
        *,
        approved: bool = False,
        expected_version: int | None = None,
        confirm: Confirmation | None = None,
    ) -> dict:
        """Create a fresh task from an approved workflow after a separate run approval."""
        if not approved:
            raise PermissionError("Replaying a workflow requires explicit approval")
        if expected_version is None:
            raise ValueError("Replay requires the reviewed workflow version")
        task_id = self.create_workflow_task(
            procedure_id,
            planner,
            expected_version=expected_version,
            approved=True,
        )
        return executor.execute(task_id, confirm=confirm)
