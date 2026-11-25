"""Local, in-memory speech onset capture for interrupting spoken output."""

from __future__ import annotations

import math
import threading
from collections import deque

import numpy as np
import sounddevice as sd


class BargeInCapture:
    """Watch one microphone during TTS and keep a bounded phrase buffer.

    Audio is kept only in memory. A short ring buffer preserves the start of a
    phrase; capture ends after silence or a fixed maximum duration.
    """

    def __init__(
        self,
        *,
        device_index: int | None,
        sample_rate: int,
        rms_threshold: float = 0.03,
        mute_event: threading.Event | None = None,
        stream_factory=None,
        block_seconds: float = 0.1,
        pre_roll_seconds: float = 0.35,
        silence_seconds: float = 0.8,
        max_duration: float = 15.0,
        trigger_blocks: int = 2,
    ) -> None:
        if device_index is not None and device_index < 0:
            raise ValueError("Barge-in microphone index cannot be negative")
        if sample_rate < 8_000:
            raise ValueError("Barge-in sample rate must be at least 8000 Hz")
        if not math.isfinite(rms_threshold) or not 0 < rms_threshold <= 1:
            raise ValueError("Barge-in RMS threshold must be from greater than zero to one")
        if (
            not math.isfinite(block_seconds)
            or block_seconds <= 0
            or not math.isfinite(pre_roll_seconds)
            or pre_roll_seconds < 0
            or not math.isfinite(silence_seconds)
            or silence_seconds <= 0
            or not math.isfinite(max_duration)
            or max_duration <= 0
            or trigger_blocks < 1
        ):
            raise ValueError("Barge-in capture timing settings are invalid")

        self.device_index = device_index
        self.sample_rate = sample_rate
        self.rms_threshold = rms_threshold
        self.mute_event = mute_event
        self.blocksize = max(1, round(sample_rate * block_seconds))
        self.pre_roll_blocks = max(1, math.ceil(pre_roll_seconds / block_seconds))
        self.silence_samples = round(silence_seconds * sample_rate)
        self.max_samples = round(max_duration * sample_rate)
        self.trigger_blocks = trigger_blocks
        self._stream_factory = stream_factory or sd.InputStream
        self._pre_roll: deque[np.ndarray] = deque(maxlen=self.pre_roll_blocks)
        self._audio_blocks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._triggered_event = threading.Event()
        self._finished_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None

    @property
    def triggered(self) -> bool:
        return self._triggered_event.is_set()

    @property
    def finished(self) -> bool:
        return self._finished_event.is_set()

    @property
    def error(self) -> Exception | None:
        return self._error

    def start(self, *, timeout: float = 3.0) -> bool:
        """Start local monitoring; return false if muted or unavailable."""
        if self._thread is not None:
            raise RuntimeError("Barge-in capture can only be started once")
        if self.mute_event is not None and self.mute_event.is_set():
            self._finished_event.set()
            return False

        self._thread = threading.Thread(
            target=self._capture,
            name="shu-barge-in-capture",
            daemon=True,
        )
        self._thread.start()
        if not self._ready_event.wait(timeout):
            self.stop()
            raise TimeoutError("Barge-in microphone did not initialize")
        return self._error is None

    def stop(self, *, timeout: float = 2.0) -> None:
        """Stop the microphone stream and wait for its thread to release."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("Barge-in microphone did not stop cleanly")
        self._finished_event.set()

    def audio(self) -> np.ndarray | None:
        """Return the interrupted phrase once capture has stopped."""
        if (
            not self.triggered
            or not self.finished
            or self._error is not None
            or (self.mute_event is not None and self.mute_event.is_set())
        ):
            return None
        with self._lock:
            blocks = tuple(self._audio_blocks)
        if not blocks:
            return None
        return np.concatenate(blocks).astype(np.float32, copy=False)

    def _capture(self) -> None:
        speech_blocks = 0
        silence_samples = 0
        captured_samples = 0
        try:
            with self._stream_factory(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                device=self.device_index,
                blocksize=self.blocksize,
            ) as stream:
                self._ready_event.set()
                while not self._stop_event.is_set():
                    if self.mute_event is not None and self.mute_event.is_set():
                        break
                    block, _overflowed = stream.read(self.blocksize)
                    if self._stop_event.is_set() or (
                        self.mute_event is not None and self.mute_event.is_set()
                    ):
                        break
                    mono = np.asarray(block, dtype=np.float32).reshape(-1)
                    if mono.size == 0 or not np.isfinite(mono).all():
                        continue
                    rms = float(
                        np.sqrt(np.mean(np.square(mono), dtype=np.float64))
                    )

                    if not self.triggered:
                        self._pre_roll.append(mono.copy())
                        speech_blocks = speech_blocks + 1 if rms >= self.rms_threshold else 0
                        if speech_blocks >= self.trigger_blocks:
                            with self._lock:
                                self._audio_blocks = [
                                    sample.copy() for sample in self._pre_roll
                                ]
                            captured_samples = sum(
                                len(sample) for sample in self._audio_blocks
                            )
                            self._triggered_event.set()
                        continue

                    with self._lock:
                        self._audio_blocks.append(mono.copy())
                    captured_samples += mono.size
                    if rms >= self.rms_threshold:
                        silence_samples = 0
                    else:
                        silence_samples += mono.size
                    if (
                        silence_samples >= self.silence_samples
                        or captured_samples >= self.max_samples
                    ):
                        break
        except Exception as error:
            self._error = error
        finally:
            self._ready_event.set()
            self._finished_event.set()
