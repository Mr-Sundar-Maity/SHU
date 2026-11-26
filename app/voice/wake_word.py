"""Local OpenWakeWord microphone listener for a supplied Hey SHU model."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from collections.abc import Callable

import numpy as np
import sounddevice as sd

WAKE_SAMPLE_RATE = 16_000
WAKE_BLOCK_SAMPLES = 1_280
WAKE_THRESHOLD = 0.55
WAKE_DEBOUNCE_SECONDS = 2.0


def load_wake_word_model(model_path: Path):
    """Load the supplied local ONNX model with OpenWakeWord's local features."""
    if model_path.suffix.casefold() != ".onnx" or not model_path.is_file():
        raise FileNotFoundError("A trained local Hey SHU ONNX model is required")
    try:
        from openwakeword.model import Model
    except ImportError as error:
        raise RuntimeError("Install openwakeword for wake-word detection") from error
    return Model(wakeword_models=[str(model_path)], inference_framework="onnx")


class WakeActivationGate:
    """Apply the same score threshold and cooldown to live and recorded audio."""

    def __init__(
        self, threshold: float = WAKE_THRESHOLD, debounce_seconds: float = WAKE_DEBOUNCE_SECONDS,
    ) -> None:
        if not 0.0 < threshold < 1.0 or not math.isfinite(debounce_seconds) or debounce_seconds < 0:
            raise ValueError("Invalid wake-word threshold or debounce interval")
        self.threshold = threshold
        self.debounce_seconds = debounce_seconds
        self._last_detection: float | None = None

    def should_activate(self, scores: dict[str, float], now: float) -> bool:
        best = max((score for score in scores.values() if math.isfinite(score)), default=0.0)
        if best < self.threshold:
            return False
        if self._last_detection is not None and now - self._last_detection < self.debounce_seconds:
            return False
        self._last_detection = now
        return True


class WakeWordListener:
    """Listen in memory only; a trained compatible wake-word model is required."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        device_index: int | None = None,
        threshold: float = WAKE_THRESHOLD,
        debounce_seconds: float = WAKE_DEBOUNCE_SECONDS,
        on_detected: Callable[[], None] | None = None,
        mute_event: threading.Event | None = None,
    ) -> None:
        self.model_path = Path(model_path).expanduser().resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError(
                "A trained Hey SHU OpenWakeWord model is required: "
                + str(self.model_path)
            )
        self.device_index = device_index
        self._gate = WakeActivationGate(threshold, debounce_seconds)
        self.on_detected = on_detected
        self.mute_event = mute_event
        self._stop = threading.Event()

    def run(self) -> None:
        """Block until stop() is requested; raw frames are never saved."""
        model = load_wake_word_model(self.model_path)
        while not self._stop.is_set():
            if self.mute_event is not None and self.mute_event.is_set():
                self._stop.wait(0.1)
                continue
            with sd.InputStream(
                samplerate=WAKE_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=WAKE_BLOCK_SAMPLES,
                device=self.device_index,
            ) as stream:
                while not self._stop.is_set() and not (
                    self.mute_event is not None and self.mute_event.is_set()
                ):
                    audio, _ = stream.read(WAKE_BLOCK_SAMPLES)
                    if self._stop.is_set() or (self.mute_event is not None and self.mute_event.is_set()):
                        break
                    scores = model.predict(np.asarray(audio).reshape(-1))
                    if self._stop.is_set() or (self.mute_event is not None and self.mute_event.is_set()):
                        break
                    if self._gate.should_activate(scores, time.monotonic()):
                        if self.on_detected:
                            self.on_detected()
                        return

    def stop(self) -> None:
        self._stop.set()
