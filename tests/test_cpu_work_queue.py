from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pytest

from app.config import Settings
from app.cpu_work_queue import CPU_WORK_QUEUE, CPUWorkQueue


def test_cpu_work_queue_serializes_jobs_in_fifo_order():
    queue = CPUWorkQueue()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    entered: list[str] = []
    lock = threading.Lock()

    def first_job():
        with queue.slot(timeout=2):
            with lock:
                entered.append("first")
            first_entered.set()
            assert release_first.wait(2)

    def second_job():
        with queue.slot(timeout=2):
            with lock:
                entered.append("second")
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_job)
        assert first_entered.wait(1)
        second = pool.submit(second_job)
        deadline = time.monotonic() + 1
        while queue.waiting_count == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert queue.waiting_count == 1
        assert not second_entered.is_set()
        release_first.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert entered == ["first", "second"]
    assert not queue.busy
    assert queue.waiting_count == 0


def test_cpu_work_queue_cancelled_waiter_leaves_queue_clean():
    queue = CPUWorkQueue()
    cancelled = threading.Event()

    def waiting_job():
        with queue.slot(timeout=2, cancel_event=cancelled):
            return "entered"

    with queue.slot(timeout=2):
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(waiting_job)
            deadline = time.monotonic() + 1
            while queue.waiting_count == 0 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert queue.waiting_count == 1
            cancelled.set()
            with pytest.raises(InterruptedError, match="Cancelled"):
                waiting.result(timeout=1)
            assert queue.waiting_count == 0

    with queue.slot(timeout=1):
        assert queue.busy


def test_cpu_work_queue_timeout_removes_waiter_without_blocking_next_job():
    queue = CPUWorkQueue()

    def waiting_job():
        with queue.slot(timeout=0.02):
            return "entered"

    with queue.slot(timeout=1):
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(waiting_job)
            with pytest.raises(TimeoutError, match="Timed out"):
                waiting.result(timeout=1)
        assert queue.waiting_count == 0

    with queue.slot(timeout=1):
        assert queue.busy


@pytest.mark.parametrize(
    "timeout", [0, -1, float("inf"), float("nan"), 10**1000, True]
)
def test_cpu_work_queue_rejects_invalid_deadlines(timeout):
    with pytest.raises(ValueError, match="finite positive"):
        with CPUWorkQueue().slot(timeout=timeout):
            pytest.fail("invalid timeout acquired the queue")


def test_local_ai_and_whisper_use_the_shared_cpu_work_queue(monkeypatch):
    from app.ai import ai_engine
    from app.voice import stt_engine

    assert ai_engine.CPU_WORK_QUEUE is CPU_WORK_QUEUE
    assert stt_engine.CPU_WORK_QUEUE is CPU_WORK_QUEUE

    class TrackingQueue:
        active = False
        entered = 0

        @contextmanager
        def slot(self, **_kwargs):
            assert not self.active
            self.active = True
            self.entered += 1
            try:
                yield
            finally:
                self.active = False

    queue = TrackingQueue()
    monkeypatch.setattr(ai_engine, "CPU_WORK_QUEUE", queue)
    monkeypatch.setattr(stt_engine, "CPU_WORK_QUEUE", queue)

    class ChatResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "READY"}}

    def fake_post(*_args, **_kwargs):
        assert queue.active
        return ChatResponse()

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)
    settings = Settings.from_env({"SHU_MICROPHONE_DEVICE": ""})
    assert ai_engine.SHUAIEngine(settings).ask_local("READY") == "READY"

    class FakeWhisperModel:
        def transcribe(self, _audio, **_kwargs):
            assert queue.active
            return iter([SimpleNamespace(text="READY")]), SimpleNamespace(
                language="en", language_probability=1.0
            )

    whisper = stt_engine.SHUSTTEngine(settings=settings)
    whisper.model = FakeWhisperModel()
    assert whisper.transcribe(np.zeros(160, dtype=np.float32))["text"] == "READY"
    assert queue.entered == 2
