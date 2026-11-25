"""Typed records shared by SHU's local persistence layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    memory_type: str
    content: str
    source: str
    sensitivity: str
    confidence: float
    approved: bool
    created_at: str
    updated_at: str
    retention_until: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    message_id: str
    conversation_id: str
    role: str
    content: str
    timestamp: str
    language: str | None = None


@dataclass(frozen=True, slots=True)
class ReminderRecord:
    reminder_id: str
    text: str
    due_at: str
    timezone: str
    recurrence: str | None
    status: str


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    request: str
    plan_json: str
    status: str
    started_at: str
    finished_at: str | None = None
