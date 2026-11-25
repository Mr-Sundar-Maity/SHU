"""FIFO coordination for CPU-heavy local AI and speech inference."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager


class CPUWorkQueue:
    """Allow one local model inference at a time, preserving request order."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._waiting: deque[object] = deque()
        self._active = False

    @property
    def waiting_count(self) -> int:
        with self._condition:
            return len(self._waiting)

    @property
    def busy(self) -> bool:
        with self._condition:
            return self._active

    @contextmanager
    def slot(
        self,
        *,
        timeout: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[None]:
        """Wait for the FIFO slot, with an optional deadline and cancellation."""
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise ValueError(
                    "CPU work queue timeout must be a finite positive number"
                )
            try:
                timeout = float(timeout)
            except (OverflowError, ValueError) as error:
                raise ValueError(
                    "CPU work queue timeout must be a finite positive number"
                ) from error
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError(
                    "CPU work queue timeout must be a finite positive number"
                )

        ticket = object()
        deadline = time.monotonic() + timeout if timeout is not None else None
        with self._condition:
            self._waiting.append(ticket)
            try:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("Cancelled while waiting for local model work")
                    if not self._active and self._waiting[0] is ticket:
                        self._waiting.popleft()
                        self._active = True
                        break
                    remaining = (
                        deadline - time.monotonic() if deadline is not None else None
                    )
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError("Timed out waiting for local model work")
                    wait_time = remaining
                    if cancel_event is not None:
                        wait_time = min(wait_time, 0.1) if wait_time is not None else 0.1
                    self._condition.wait(wait_time)
            except BaseException:
                self._waiting.remove(ticket)
                self._condition.notify_all()
                raise

        try:
            yield
        finally:
            with self._condition:
                self._active = False
                self._condition.notify_all()


CPU_WORK_QUEUE = CPUWorkQueue()
