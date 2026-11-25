"""Allowlisted, validated tool execution with approvals and audit records."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Mapping

from app.security.emergency_stop import EmergencyStop
from app.security.policy import PermissionPolicy, RiskLevel
from database.database import Database


Validator = Callable[[Mapping[str, Any]], dict[str, Any]]
Handler = Callable[..., Any]
Confirmation = Callable[[str, Mapping[str, Any], RiskLevel], bool]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    risk: RiskLevel
    handler: Handler
    validator: Validator
    verifier: Callable[[Any, Mapping[str, Any]], bool] | None = None
    requires_approval: bool = False
    estimate_seconds: int = 5
    resources: tuple[str, ...] = ()
    retry_limit: int = 0

    def __post_init__(self) -> None:
        if type(self.estimate_seconds) is not int or not 1 <= self.estimate_seconds <= 3_600:
            raise ValueError("Tool estimate must be an integer from 1 to 3600 seconds")
        if not isinstance(self.resources, tuple) or any(
            not isinstance(resource, str)
            or not resource
            or len(resource) > 40
            or not resource.replace("_", "").isalnum()
            or resource.lower() != resource
            for resource in self.resources
        ):
            raise ValueError("Tool resources must be lowercase identifiers")
        if len(set(self.resources)) != len(self.resources):
            raise ValueError("Tool resources must be unique")
        if type(self.retry_limit) is not int or not 0 <= self.retry_limit <= 2:
            raise ValueError("Tool retry limit must be an integer from 0 to 2")
        if self.retry_limit and self.risk is not RiskLevel.READ_ONLY:
            raise ValueError("Automatic retries are limited to read-only tools")


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool: str
    success: bool
    value: Any = None
    error_code: str | None = None
    verified: bool = False


class ToolRegistry:
    """Never executes model-generated code; calls registered functions only."""

    def __init__(
        self,
        database: Database,
        *,
        policy: PermissionPolicy | None = None,
        emergency_stop: EmergencyStop | None = None,
        automation_enabled: bool = True,
    ) -> None:
        if type(automation_enabled) is not bool:
            raise TypeError("automation_enabled must be a bool")
        self.database = database
        self.policy = policy or PermissionPolicy()
        self.emergency_stop = emergency_stop or EmergencyStop()
        self._automation_enabled = automation_enabled
        self._automation_lock = threading.Lock()
        self._tools: dict[str, ToolSpec] = {}

    @property
    def automation_enabled(self) -> bool:
        with self._automation_lock:
            return self._automation_enabled

    def set_automation_enabled(self, enabled: bool) -> None:
        """Enable or block registered automation at execution boundaries."""
        if type(enabled) is not bool:
            raise TypeError("automation_enabled must be a bool")
        with self._automation_lock:
            self._automation_enabled = enabled

    def register(self, spec: ToolSpec) -> None:
        if not spec.name.isidentifier():
            raise ValueError("Tool name must be a Python identifier")
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def list_tools(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools.values())

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        confirm: Confirmation | None = None,
        task_id: str | None = None,
    ) -> ToolResult:
        self.emergency_stop.check()
        if name not in self._tools:
            self._audit(task_id, name, RiskLevel.CRITICAL, "denied", "unknown_tool")
            raise PermissionError("Tool is not registered")
        spec = self._tools[name]
        if not self.automation_enabled:
            self._audit(task_id, name, spec.risk, "denied", "automation_disabled")
            raise PermissionError("SHU automation is disabled in settings")
        if not isinstance(arguments, Mapping):
            self._audit(task_id, name, spec.risk, "denied", "invalid_arguments")
            raise TypeError("Tool arguments must be an object")

        try:
            validated = spec.validator(arguments)
        except Exception:
            self._audit(task_id, name, spec.risk, "denied", "validation_error")
            raise

        approved = False
        approval_required = spec.requires_approval or spec.risk >= RiskLevel.MODIFICATION
        if approval_required:
            approved = bool(confirm and confirm(name, validated, spec.risk))
        if spec.requires_approval and not approved:
            self._audit(task_id, name, spec.risk, "denied", "approval_required")
            raise PermissionError("This read action requires explicit user approval")
        try:
            self.policy.authorize(spec.risk, approved=approved)
        except PermissionError:
            self._audit(task_id, name, spec.risk, "denied", "approval_required")
            raise

        if not self.automation_enabled:
            self._audit(task_id, name, spec.risk, "denied", "automation_disabled")
            raise PermissionError("SHU automation is disabled in settings")

        self.emergency_stop.check()
        started = perf_counter()
        try:
            value = spec.handler(**validated)
        except Exception as error:
            self._audit(
                task_id,
                name,
                spec.risk,
                "approved",
                type(error).__name__,
                duration_ms=_elapsed_ms(started),
            )
            raise
        verified = spec.risk is RiskLevel.READ_ONLY
        if spec.verifier is not None:
            try:
                verified = bool(spec.verifier(value, validated))
            except Exception as error:
                self._audit(
                    task_id,
                    name,
                    spec.risk,
                    "approved",
                    type(error).__name__,
                    duration_ms=_elapsed_ms(started),
                )
                raise
            if not verified:
                self._audit(
                    task_id,
                    name,
                    spec.risk,
                    "approved",
                    "verification_failed",
                    duration_ms=_elapsed_ms(started),
                )
                raise RuntimeError("Tool postcondition verification failed")
        self._audit(
            task_id,
            name,
            spec.risk,
            "approved" if approved else "not_required",
            "success",
            duration_ms=_elapsed_ms(started),
        )
        return ToolResult(tool=name, success=True, value=value, verified=verified)

    def _audit(
        self,
        task_id: str | None,
        name: str,
        risk: RiskLevel,
        approval: str,
        result: str,
        *,
        duration_ms: int | None = None,
    ) -> None:
        summary = {"tool": name}
        if duration_ms is not None:
            summary["duration_ms"] = duration_ms
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    """INSERT INTO audit_logs
                    (log_id,task_id,actor,tool,action_summary,risk,approval,result,error_code,timestamp)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()),
                        task_id,
                        "tool_registry",
                        name,
                        json.dumps(summary, separators=(",", ":")),
                        f"L{int(risk)}",
                        approval,
                        result,
                        None if result == "success" else result,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    ),
                )


def _elapsed_ms(started: float) -> int:
    """Return a nonnegative, argument-free tool execution duration."""
    return max(0, round((perf_counter() - started) * 1_000))
