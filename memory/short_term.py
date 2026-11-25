"""Bounded in-process conversation memory."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class Turn:
    role: str
    content: str
    timestamp: str


class ShortTermMemory:
    def __init__(self, max_turns: int = 20) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be positive")
        self._turns: deque[Turn] = deque(maxlen=max_turns)

    def add(self, role: str, content: str) -> None:
        if role not in {"user", "assistant", "system", "tool"}:
            raise ValueError("Unsupported conversation role")
        if not content.strip():
            return
        self._turns.append(
            Turn(role, content.strip(), datetime.now(timezone.utc).isoformat())
        )

    def recent(self) -> list[Turn]:
        return list(self._turns)

    def clear(self) -> None:
        self._turns.clear()
