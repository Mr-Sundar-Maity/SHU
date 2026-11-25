import sqlite3

import pytest

from app.learning.learning_service import LearningService
from app.security.policy import RiskLevel
from app.security.registry import ToolRegistry, ToolSpec
from app.tasks.executor import TaskExecutor
from app.tasks.planner import InvalidPlan, TaskPlanner
from database.database import Database


def test_preferences_are_approved_audited_and_reversible(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    learning = LearningService(database)

    with pytest.raises(PermissionError):
        learning.save_preference("language", "Bengali")
    learning.save_preference("language", "bn", approved=True)
    assert learning.get_preference("language") == "bn"
    assert learning.delete_preference("language", approved=True)
    assert learning.get_preference("language") is None
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 2


def test_learning_never_stores_authentication_secrets(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    learning = LearningService(database)
    with pytest.raises(ValueError, match="cannot be stored"):
        learning.save_preference("api_key", "value", approved=True)
    with pytest.raises(ValueError, match="cannot be stored"):
        learning.save_preference("password_hint", "first pet", approved=True)
    with pytest.raises(ValueError, match="cannot be stored"):
        learning.save_preference("favorite_topic", "my access token", approved=True)


def test_workflow_replay_is_revalidated_and_requires_approval(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    learning = LearningService(database)
    registry = ToolRegistry(database)
    calls = []
    registry.register(
        ToolSpec(
            name="read_value",
            description="Read a value",
            risk=RiskLevel.READ_ONLY,
            handler=lambda key: calls.append(key) or key,
            validator=lambda args: {"key": args["key"]},
        )
    )
    planner = TaskPlanner(database, registry)
    executor = TaskExecutor(database, planner, registry)
    procedure_id = learning.save_workflow(
        "Read a preference",
        [{"tool": "read_value", "arguments": {"key": "language"}}],
        approved=True,
    )

    preview = learning.preview_workflow(procedure_id, planner)
    assert preview["name"] == "Read a preference"
    with pytest.raises(PermissionError, match="explicit approval"):
        learning.run_workflow(procedure_id, planner, executor)
    report = learning.run_workflow(
        procedure_id,
        planner,
        executor,
        approved=True,
        expected_version=preview["version"],
    )
    assert report["status"] == "completed"
    assert calls == ["language"]

    with database.connect() as connection:
        with connection:
            connection.execute(
                "UPDATE procedural_memories SET steps_json=? WHERE procedure_id=?",
                ('[{"tool":"powershell","arguments":{}}]', procedure_id),
            )
    with pytest.raises(InvalidPlan, match="unregistered"):
        learning.preview_workflow(procedure_id, planner)


def test_workflow_replay_refuses_a_newly_approved_version(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    learning = LearningService(database)
    registry = ToolRegistry(database)
    registry.register(
        ToolSpec(
            name="read_value",
            description="Read a value",
            risk=RiskLevel.READ_ONLY,
            handler=lambda key: key,
            validator=lambda args: {"key": args["key"]},
        )
    )
    planner = TaskPlanner(database, registry)
    procedure_id = learning.save_workflow(
        "Read a preference",
        [{"tool": "read_value", "arguments": {"key": "language"}}],
        approved=True,
    )
    reviewed = learning.preview_workflow(procedure_id, planner)

    learning.update_workflow(
        procedure_id,
        "Read a preference",
        [{"tool": "read_value", "arguments": {"key": "theme"}}],
        planner,
        approved=True,
    )
    learning.approve_workflow(procedure_id, planner, approved=True)

    with pytest.raises(ValueError, match="changed since review"):
        learning.create_workflow_task(
            procedure_id,
            planner,
            expected_version=reviewed["version"],
            approved=True,
        )
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_workflow_task_insert_uses_the_version_check_transaction(tmp_path, monkeypatch):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    learning = LearningService(database)
    registry = ToolRegistry(database)
    registry.register(
        ToolSpec(
            name="read_value",
            description="Read a value",
            risk=RiskLevel.READ_ONLY,
            handler=lambda key: key,
            validator=lambda args: {"key": args["key"]},
        )
    )
    planner = TaskPlanner(database, registry)
    procedure_id = learning.save_workflow(
        "Read a preference",
        [{"tool": "read_value", "arguments": {"key": "language"}}],
        approved=True,
    )
    reviewed = learning.preview_workflow(procedure_id, planner)
    original_create = planner.create

    def check_transaction(request, steps, *, connection=None):
        assert connection is not None
        assert connection.in_transaction
        with database.connect() as competing_connection:
            competing_connection.execute("PRAGMA busy_timeout=0")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                with competing_connection:
                    competing_connection.execute(
                        "UPDATE procedural_memories SET approval_status='revoked' "
                        "WHERE procedure_id=?",
                        (procedure_id,),
                    )
        task_id = original_create(request, steps, connection=connection)
        assert connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone() is not None
        return task_id

    monkeypatch.setattr(planner, "create", check_transaction)

    task_id = learning.create_workflow_task(
        procedure_id,
        planner,
        expected_version=reviewed["version"],
        approved=True,
    )

    with database.connect() as connection:
        task = connection.execute(
            "SELECT status,plan_json FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
    assert task["status"] == "planned"
    assert '"key": "language"' in task["plan_json"]


def test_task_feedback_is_approved_local_audited_and_secret_filtered(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    with database.connect() as connection:
        with connection:
            connection.execute(
                "INSERT INTO tasks(task_id,request,status,started_at) VALUES(?,?,?,?)",
                ("task-1", "Create a report", "completed", "2026-01-01T00:00:00+00:00"),
            )
    learning = LearningService(database)

    with pytest.raises(PermissionError, match="user approval"):
        learning.record_task_feedback("task-1", "helpful")
    with pytest.raises(ValueError, match="Credential-related"):
        learning.record_task_feedback(
            "task-1", "needs_improvement", "remember my access token", approved=True
        )
    with pytest.raises(KeyError, match="Task not found"):
        learning.record_task_feedback("missing", "helpful", approved=True)

    feedback_id = learning.record_task_feedback(
        "task-1", "needs_improvement", "Use a shorter title", approved=True
    )

    feedback = learning.list_task_feedback("task-1")
    assert len(feedback) == 1
    assert feedback[0]["feedback_id"] == feedback_id
    assert feedback[0]["rating"] == "needs_improvement"
    assert feedback[0]["correction"] == "Use a shorter title"
    assert feedback[0]["timestamp"]


def test_workflow_edit_requires_reapproval_and_revoke_disables_replay(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    learning = LearningService(database)
    registry = ToolRegistry(database)
    registry.register(
        ToolSpec(
            name="read_value",
            description="Read a value",
            risk=RiskLevel.READ_ONLY,
            handler=lambda key: key,
            validator=lambda args: {"key": args["key"]},
        )
    )
    planner = TaskPlanner(database, registry)
    procedure_id = learning.save_workflow(
        "Read workflow",
        [{"tool": "read_value", "arguments": {"key": "before"}}],
        approved=True,
    )

    with pytest.raises(PermissionError, match="explicit approval"):
        learning.update_workflow(
            procedure_id,
            "Edited workflow",
            [{"tool": "read_value", "arguments": {"key": "after"}}],
            planner,
        )
    with pytest.raises(InvalidPlan, match="unregistered"):
        learning.update_workflow(
            procedure_id,
            "Unsafe edit",
            [{"tool": "powershell", "arguments": {}}],
            planner,
            approved=True,
        )

    learning.update_workflow(
        procedure_id,
        "Edited workflow",
        [{"tool": "read_value", "arguments": {"key": "after"}}],
        planner,
        approved=True,
    )
    record = learning.procedures.get(procedure_id)
    assert record["approval_status"] == "pending"
    assert record["version"] == 2
    with pytest.raises(KeyError, match="Approved workflow"):
        learning.preview_workflow(procedure_id, planner)

    learning.approve_workflow(procedure_id, planner, approved=True)
    assert learning.preview_workflow(procedure_id, planner)["name"] == "Edited workflow"
    with pytest.raises(PermissionError, match="explicit approval"):
        learning.revoke_workflow(procedure_id)
    learning.revoke_workflow(procedure_id, approved=True)
    assert learning.procedures.get(procedure_id)["approval_status"] == "revoked"
    with pytest.raises(KeyError, match="Approved workflow"):
        learning.preview_workflow(procedure_id, planner)
