"""Checkpointed task execution and postcondition verification."""

from __future__ import annotations

import errno
import json
import os
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.security.registry import Confirmation, ToolRegistry
from app.tasks.planner import TaskPlanner
from database.database import Database


Verifier = Callable[[Any, dict[str, Any]], bool]
_RETRY_BACKOFF_BASE_SECONDS = 0.5
_RETRY_BACKOFF_MAX_SECONDS = 2.0


class TaskExecutor:
    def __init__(
        self,
        database: Database,
        planner: TaskPlanner,
        registry: ToolRegistry,
        *,
        verifiers: dict[str, Verifier] | None = None,
    ) -> None:
        self.database = database
        self.planner = planner
        self.registry = registry
        self.verifiers = verifiers or {}

    def reconcile_orphaned_tasks(self) -> list[dict[str, Any]]:
        """Classify work left running by a dead process; never replay it here."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            candidates = connection.execute(
                "SELECT task_id,runner_pid,inflight_step,plan_json,checkpoint_json "
                "FROM tasks WHERE status='running'"
            ).fetchall()
        recovered: list[dict[str, Any]] = []
        for row in candidates:
            runner_pid = row["runner_pid"]
            if runner_pid is not None and _process_is_alive(int(runner_pid)):
                continue
            try:
                steps = json.loads(row["plan_json"])
                checkpoint = json.loads(row["checkpoint_json"])
            except (TypeError, json.JSONDecodeError):
                steps, checkpoint = [], []
            status, uncertain_step = _classify_orphaned_checkpoint(
                steps, checkpoint, row["inflight_step"]
            )
            if status == "interrupted" and uncertain_step is None:
                uncertain_step = max(1, min(len(steps), 1)) if steps else None
            with self.database.connect() as connection:
                with connection:
                    cursor = connection.execute(
                        "UPDATE tasks SET status=?,finished_at=?,runner_pid=NULL,inflight_step=? "
                        "WHERE task_id=? AND status='running' AND runner_pid IS ? "
                        "AND inflight_step IS ? AND checkpoint_json=?",
                        (
                            status, now, uncertain_step, row["task_id"], runner_pid,
                            row["inflight_step"], row["checkpoint_json"],
                        ),
                    )
                    if cursor.rowcount != 1:
                        continue
                    connection.execute(
                        "INSERT INTO audit_logs(log_id,task_id,actor,tool,action_summary,risk,approval,result,timestamp) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            str(uuid.uuid4()),
                            row["task_id"],
                            "task_recovery",
                            "reconcile_orphaned_task",
                            json.dumps({"inflight_step": uncertain_step}),
                            "L1",
                            "system",
                            status,
                            now,
                        ),
                    )
            recovered.append(
                {"task_id": row["task_id"], "status": status, "uncertain_step": uncertain_step}
            )
        return recovered

    def preview_interrupted(self, task_id: str) -> dict[str, Any]:
        """Expose the uncertain step so a person can inspect it before recovery."""
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT request,status,plan_json,checkpoint_json,inflight_step FROM tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Task not found")
        if row["status"] != "interrupted":
            raise ValueError("Task is not awaiting interrupted-task review")
        steps = self.planner.validate_steps(json.loads(row["plan_json"]))
        checkpoint = json.loads(row["checkpoint_json"])
        if checkpoint == {}:
            checkpoint = []
        if not isinstance(checkpoint, list):
            raise ValueError("The interrupted task checkpoint is invalid")
        uncertain_step = row["inflight_step"]
        if isinstance(uncertain_step, bool) or not isinstance(uncertain_step, int):
            raise ValueError("The interrupted task has no recoverable step index")
        if not 1 <= uncertain_step <= len(steps):
            raise ValueError("The interrupted task step index is invalid")
        completed = checkpoint[: uncertain_step - 1]
        if len(completed) != uncertain_step - 1 or any(
            not isinstance(item, dict)
            or item.get("step") != index
            or item.get("status") != "verified"
            for index, item in enumerate(completed, start=1)
        ):
            raise ValueError("The task checkpoint does not have a verified prefix")
        return {
            "task_id": task_id,
            "request": row["request"],
            "completed": completed,
            "uncertain_step_number": uncertain_step,
            "uncertain_step": steps[uncertain_step - 1],
            "remaining_after_uncertain_step": steps[uncertain_step:],
        }

    def resolve_interrupted(
        self,
        task_id: str,
        *,
        action: str,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Record a human-reviewed outcome without automatically running work."""
        if not approved:
            raise PermissionError("Resolving an interrupted task requires explicit approval")
        if action not in {"retry", "accept_complete"}:
            raise ValueError("action must be retry or accept_complete")
        preview = self.preview_interrupted(task_id)
        step_number = preview["uncertain_step_number"]
        steps = self.planner.get_steps(task_id)
        checkpoint = list(preview["completed"])
        current_tool = preview["uncertain_step"]["tool"]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if action == "retry":
            checkpoint.append(
                {
                    "step": step_number,
                    "status": "cancelled",
                    "recovery_choice": "user_confirmed_not_performed",
                }
            )
            status = "cancelled"
        else:
            checkpoint.append(
                {
                    "step": step_number,
                    "status": "verified",
                    "tool": current_tool,
                    "verification": "user_reviewed_after_interruption",
                }
            )
            if step_number < len(steps):
                checkpoint.append(
                    {
                        "step": step_number + 1,
                        "status": "cancelled",
                        "recovery_choice": "continue_after_user_review",
                    }
                )
                status = "cancelled"
            else:
                status = "completed_manual_review"
        with self.database.connect() as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE tasks SET status=?,checkpoint_json=?,finished_at=?,runner_pid=NULL,inflight_step=NULL "
                    "WHERE task_id=? AND status='interrupted'",
                    (
                        status,
                        json.dumps(checkpoint),
                        now if status == "completed_manual_review" else None,
                        task_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Task is no longer awaiting interrupted-task review")
                connection.execute(
                    "INSERT INTO audit_logs(log_id,task_id,actor,tool,action_summary,risk,approval,result,timestamp) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4()),
                        task_id,
                        "task_recovery",
                        "resolve_interrupted_task",
                        json.dumps({"step": step_number, "action": action}),
                        "L2",
                        "approved",
                        status,
                        now,
                    ),
                )
        return {
            "task_id": task_id,
            "status": status,
            "resolved_step": step_number,
            "tool": current_tool,
            "next_action": "resume" if status == "cancelled" else "none",
        }

    def execute(
        self,
        task_id: str,
        *,
        confirm: Confirmation | None = None,
        resume: bool = False,
        on_progress: Callable[[int, int, str, str], None] | None = None,
        expected_request: str | None = None,
        expected_steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        steps = self.planner.get_steps(task_id)
        if not self.registry.automation_enabled:
            raise PermissionError("SHU automation is disabled; task remains queued")
        if expected_steps is not None:
            reviewed_steps = self.planner.validate_steps(expected_steps)
            if steps != reviewed_steps:
                raise ValueError("Task plan changed after review; preview it again")
        for step in steps:
            verifier_name = step["verify"]
            if verifier_name and verifier_name not in self.verifiers:
                raise ValueError(f"Verifier is not registered: {verifier_name}")
        if resume:
            completed, start_index, checkpoint_json = self._recovery_state(task_id, steps)
            self._claim_task(
                task_id,
                allowed_statuses=("cancelled", "partially_completed"),
                expected_request=expected_request,
                expected_steps=steps if expected_steps is not None else None,
                expected_checkpoint_json=checkpoint_json,
            )
            results = list(completed)
        else:
            self._claim_task(
                task_id,
                allowed_statuses=("planned",),
                expected_request=expected_request,
                expected_steps=steps if expected_steps is not None else None,
            )
            results = []
            start_index = 0
        status = "completed"

        for index in range(start_index, len(steps)):
            step = steps[index]
            verified_steps = {
                item.get("step")
                for item in results
                if isinstance(item, dict) and item.get("status") == "verified"
            }
            missing_dependencies = [
                dependency
                for dependency in step["depends_on"]
                if dependency not in verified_steps
            ]
            if missing_dependencies:
                results.append(
                    {
                        "step": index + 1,
                        "status": "blocked",
                        "tool": step["tool"],
                        "missing_dependencies": missing_dependencies,
                    }
                )
                self._save_checkpoint(task_id, results)
                self._notify_progress(
                    on_progress, index + 1, len(steps), "blocked", step["tool"]
                )
                status = "failed"
                break
            try:
                self.registry.emergency_stop.check()
            except InterruptedError:
                status = "cancelled" if not results else "partially_completed"
                results.append({"step": index + 1, "status": "cancelled"})
                self._save_checkpoint(task_id, results)
                self._notify_progress(on_progress, index + 1, len(steps), "cancelled", step["tool"])
                break
            self._notify_progress(on_progress, index + 1, len(steps), "running", step["tool"])
            self._mark_inflight(task_id, index + 1)
            attempts = step["retries"] + 1
            success = False
            cancelled_by_stop = False
            last_error: Exception | None = None
            for attempt in range(attempts):
                if attempt:
                    delay = min(
                        _RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                        _RETRY_BACKOFF_MAX_SECONDS,
                    )
                    if self.registry.emergency_stop.wait_for_stop(delay):
                        cancelled_by_stop = True
                        break
                try:
                    self.registry.emergency_stop.check()
                    result = self.registry.execute(
                        step["tool"],
                        step["arguments"],
                        confirm=confirm,
                        task_id=task_id,
                    )
                    if not result.success:
                        raise RuntimeError(result.error_code or "tool failed")
                    verifier_name = step["verify"]
                    verified = result.verified
                    if verifier_name:
                        verified = self.verifiers[verifier_name](result.value, step["arguments"])
                    if not verified:
                        raise RuntimeError("postcondition verification failed")
                    results.append(
                        {"step": index + 1, "status": "verified", "tool": step["tool"]}
                    )
                    self._save_checkpoint(task_id, results)
                    self._notify_progress(on_progress, index + 1, len(steps), "verified", step["tool"])
                    success = True
                    break
                except InterruptedError as error:
                    last_error = error
                    if self.registry.emergency_stop.is_stopped:
                        cancelled_by_stop = True
                    break
                except Exception as error:
                    last_error = error
                    if not step["idempotent"] or not _is_transient_tool_error(error):
                        break
            if cancelled_by_stop:
                status = "cancelled" if not results else "partially_completed"
                results.append({"step": index + 1, "status": "cancelled"})
                self._save_checkpoint(task_id, results)
                self._notify_progress(
                    on_progress, index + 1, len(steps), "cancelled", step["tool"]
                )
                break
            if not success:
                current_tool = next(
                    spec for spec in self.registry.list_tools() if spec.name == step["tool"]
                )
                uncertain_side_effect = current_tool.risk.value >= 1
                status = "partially_completed" if results or uncertain_side_effect else "failed"
                results.append(
                    {
                        "step": index + 1,
                        "status": "failed",
                        "tool": step["tool"],
                        "error": type(last_error).__name__ if last_error else "unknown",
                    }
                )
                self._save_checkpoint(task_id, results)
                self._notify_progress(on_progress, index + 1, len(steps), "failed", step["tool"])
                break

        self._set_status(task_id, status, finished=True)
        return {"task_id": task_id, "status": status, "steps": results}

    @staticmethod
    def _notify_progress(
        callback: Callable[[int, int, str, str], None] | None,
        current: int,
        total: int,
        status: str,
        tool: str,
    ) -> None:
        if callback is None:
            return
        try:
            callback(current, total, status, tool)
        except Exception:
            # A UI progress callback must never interrupt task-state persistence.
            return

    def preview_resume(self, task_id: str) -> dict[str, Any]:
        """Return verified completed steps and the safe unstarted suffix."""
        steps = self.planner.get_steps(task_id)
        completed, start_index, _checkpoint_json = self._recovery_state(task_id, steps)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT request FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        return {
            "task_id": task_id,
            "request": row["request"],
            "completed": list(completed),
            "resume_from_step": start_index + 1,
            "remaining": steps[start_index:],
        }

    def resume(
        self,
        task_id: str,
        *,
        confirm: Confirmation | None = None,
    ) -> dict[str, Any]:
        """Continue only after a stop between verified steps; never replay failure."""
        return self.execute(task_id, confirm=confirm, resume=True)

    def _recovery_state(
        self,
        task_id: str,
        steps: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, str]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT status,checkpoint_json FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Task not found")
        if row["status"] not in {"cancelled", "partially_completed"}:
            raise ValueError("Only a task stopped between steps can be resumed")
        try:
            checkpoint = json.loads(row["checkpoint_json"])
        except json.JSONDecodeError as error:
            raise ValueError("Task checkpoint is invalid") from error
        if not isinstance(checkpoint, list) or not checkpoint:
            raise ValueError("Task has no safe recovery checkpoint")
        cancelled = checkpoint[-1]
        if not isinstance(cancelled, dict) or cancelled.get("status") != "cancelled":
            raise ValueError("A failed or uncertain action cannot be resumed automatically")
        step_number = cancelled.get("step")
        if isinstance(step_number, bool) or not isinstance(step_number, int):
            raise ValueError("Recovery checkpoint has an invalid step number")
        if not 1 <= step_number <= len(steps) or len(checkpoint) != step_number:
            raise ValueError("Recovery checkpoint does not match the saved plan")
        completed = checkpoint[:-1]
        if any(
            not isinstance(item, dict)
            or item.get("step") != index
            or item.get("status") != "verified"
            for index, item in enumerate(completed, start=1)
        ):
            raise ValueError("Only a verified completed prefix can be resumed")
        return completed, step_number - 1, row["checkpoint_json"]

    def _claim_task(
        self,
        task_id: str,
        *,
        allowed_statuses: tuple[str, ...],
        expected_request: str | None = None,
        expected_steps: list[dict[str, Any]] | None = None,
        expected_checkpoint_json: str | None = None,
    ) -> None:
        placeholders = ",".join("?" for _ in allowed_statuses)
        with self.database.connect() as connection:
            with connection:
                expected_plan_json = None
                request_guard = expected_request
                if expected_steps is not None or expected_request is not None:
                    row = connection.execute(
                        "SELECT request,plan_json FROM tasks WHERE task_id=?",
                        (task_id,),
                    ).fetchone()
                    if row is None:
                        raise KeyError("Task not found")
                    saved_steps = self.planner.validate_steps(json.loads(row["plan_json"]))
                    if expected_steps is not None and saved_steps != expected_steps:
                        raise ValueError("Task plan changed after review; preview it again")
                    if expected_request is not None and row["request"] != expected_request:
                        raise ValueError("Task request changed after review; preview it again")
                    expected_plan_json = row["plan_json"]
                    request_guard = row["request"]

                plan_condition = " AND plan_json=?" if expected_plan_json is not None else ""
                request_condition = " AND request=?" if request_guard is not None else ""
                checkpoint_condition = " AND checkpoint_json=?" if expected_checkpoint_json is not None else ""
                cursor = connection.execute(
                    f"UPDATE tasks SET status='running', finished_at=NULL,runner_pid=?,inflight_step=NULL "
                    f"WHERE task_id=? AND status IN ({placeholders})"
                    f"{plan_condition}{request_condition}{checkpoint_condition}",
                    (
                        os.getpid(),
                        task_id,
                        *allowed_statuses,
                        *((expected_plan_json,) if expected_plan_json is not None else ()),
                        *((request_guard,) if request_guard is not None else ()),
                        *((expected_checkpoint_json,) if expected_checkpoint_json is not None else ()),
                    ),
                )
                if cursor.rowcount != 1:
                    if expected_checkpoint_json is not None:
                        raise ValueError("Task checkpoint changed or task is no longer eligible; review it again")
                    raise ValueError("Task is already running or is not eligible for execution")

    def _set_status(self, task_id: str, status: str, *, finished: bool = False) -> None:
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    "UPDATE tasks SET status=?, finished_at=?,runner_pid=NULL,inflight_step=NULL WHERE task_id=?",
                    (
                        status,
                        datetime.now(timezone.utc).isoformat(timespec="seconds") if finished else None,
                        task_id,
                    ),
                )

    def _save_checkpoint(self, task_id: str, results: list[dict[str, Any]]) -> None:
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    "UPDATE tasks SET checkpoint_json=?,inflight_step=NULL WHERE task_id=?",
                    (json.dumps(results), task_id),
                )

    def _mark_inflight(self, task_id: str, step_number: int) -> None:
        with self.database.connect() as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE tasks SET inflight_step=? WHERE task_id=? AND status='running' AND runner_pid=?",
                    (step_number, task_id, os.getpid()),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Task execution ownership was lost")


def _classify_orphaned_checkpoint(
    steps: Any,
    checkpoint: Any,
    inflight_step: int | None,
) -> tuple[str, int | None]:
    # A resumed action keeps its old cancellation marker until the new outcome
    # is committed. The in-flight marker is the newer and safer evidence.
    if inflight_step is not None:
        if isinstance(steps, list) and type(inflight_step) is int and 1 <= inflight_step <= len(steps):
            return "interrupted", inflight_step
        return "interrupted", None
    if not isinstance(steps, list) or not steps or not isinstance(checkpoint, list):
        return "interrupted", 1 if isinstance(steps, list) and steps else None
    verified_prefix = 0
    for index, item in enumerate(checkpoint, start=1):
        if not isinstance(item, dict) or item.get("step") != index:
            break
        if item.get("status") == "verified":
            verified_prefix += 1
            continue
        if item.get("status") == "cancelled":
            if verified_prefix == index - 1 and index <= len(steps):
                return "cancelled", None
        break
    if verified_prefix == len(steps) and len(checkpoint) == len(steps):
        return "completed", None
    if checkpoint and isinstance(checkpoint[-1], dict):
        marker = checkpoint[-1]
        marker_step = marker.get("step")
        if marker.get("status") == "failed" and isinstance(marker_step, int):
            return "interrupted", marker_step
    inferred = verified_prefix + 1
    return "interrupted", inferred if inferred <= len(steps) else None


def _is_transient_tool_error(
    error: Exception,
    _seen: set[int] | None = None,
) -> bool:
    """Retry only recognizable transient network/transport failures."""
    seen = set() if _seen is None else _seen
    if id(error) in seen:
        return False
    seen.add(id(error))

    if isinstance(error, InterruptedError):
        return False
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True

    if isinstance(error, OSError) and error.errno in {
        errno.EAGAIN,
        errno.ECONNABORTED,
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.EHOSTUNREACH,
        errno.ENETDOWN,
        errno.ENETUNREACH,
        errno.ETIMEDOUT,
    }:
        return True

    class_names = {base.__name__.casefold() for base in type(error).__mro__}
    if class_names.intersection(
        {
            "timeout",
            "timeouterror",
            "connecttimeout",
            "connecttimeouterror",
            "readtimeout",
            "readtimeouterror",
            "connectionerror",
            "connecterror",
            "connectionreseterror",
            "connectionabortederror",
            "newconnectionerror",
            "protocolerror",
            "remoteprotocolerror",
            "temporarilyunavailable",
        }
    ):
        return True

    status = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if status is None and "httperror" in class_names:
        status = getattr(error, "code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status in {408, 425, 429} or 500 <= status <= 599

    try:
        message = str(error).casefold()
    except Exception:
        message = ""
    if any(
        marker in message
        for marker in (
            "net::err_connection_aborted",
            "net::err_connection_closed",
            "net::err_connection_refused",
            "net::err_connection_reset",
            "net::err_internet_disconnected",
            "net::err_name_not_resolved",
            "net::err_network_changed",
            "net::err_timed_out",
        )
    ):
        return True

    for attribute in ("reason", "__cause__", "__context__"):
        nested = getattr(error, attribute, None)
        if (
            isinstance(nested, Exception)
            and nested is not error
            and _is_transient_tool_error(nested, seen)
        ):
            return True
    return False


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied means fail closed as alive.
        try:
            result = kernel32.WaitForSingleObject(handle, 0)
            return result == 0x00000102 or result not in {0, 0xFFFFFFFF}
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
