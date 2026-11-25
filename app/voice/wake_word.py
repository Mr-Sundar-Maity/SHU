"""Local OpenWakeWord microphone listener for a supplied Hey SHU model."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from collections.abc import Callable

import numpy as np
import sounddevice as sd


class WakeWordListener:
    """Listen in memory only; a trained compatible wake-word model is required."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        device_index: int | None = None,
        threshold: float = 0.55,
        debounce_seconds: float = 2.0,
        on_detected: Callable[[], None] | None = None,
        mute_event: threading.Event | None = None,
    ) -> None:
        self.model_path = Path(model_path).expanduser().resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError(
                "A trained Hey SHU OpenWakeWord model is required: "
                + str(self.model_path)
            )
        if not 0.0 < threshold < 1.0 or debounce_seconds < 0:
            raise ValueError("Invalid wake-word threshold or debounce interval")
        self.device_index = device_index
        self.threshold = threshold
        self.debounce_seconds = debounce_seconds
        self.on_detected = on_detected
        self.mute_event = mute_event
        self._stop = threading.Event()
        self._model = None
        self._last_detection = 0.0

    def run(self) -> None:
        """Block until stop() is requested; raw frames are never saved."""
        try:
            from openwakeword.model import Model
        except ImportError as error:
            raise RuntimeError("Install openwakeword for wake-word detection") from error
        self._model = Model(
            wakeword_models=[str(self.model_path)],
            inference_framework="onnx",
        )
        while not self._stop.is_set():
            if self.mute_event is not None and self.mute_event.is_set():
                self._stop.wait(0.1)
                continue
            with sd.InputStream(
                samplerate=16_000,
                channels=1,
                dtype="int16",
                blocksize=1280,
                device=self.device_index,
            ) as stream:
                while not self._stop.is_set() and not (
                    self.mute_event is not None and self.mute_event.is_set()
                ):
                    audio, _ = stream.read(1280)
                    if self.mute_event is not None and self.mute_event.is_set():
                        continue
                    scores = self._model.predict(np.asarray(audio).reshape(-1))
                    if self._should_activate(scores, time.monotonic()):
                        if self.on_detected:
                            self.on_detected()
                        return

    def stop(self) -> None:
        self._stop.set()

    def _should_activate(self, scores: dict[str, float], now: float) -> bool:
        best = max(scores.values(), default=0.0)
        if best < self.threshold or now - self._last_detection < self.debounce_seconds:
            return False
        self._last_detection = now
        return True
