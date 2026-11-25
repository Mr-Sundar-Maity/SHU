"""Microphone-based speech-to-text support for SHU."""

from __future__ import annotations

import time
import threading
from collections.abc import Callable
from typing import Any

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from app.config import Settings, get_settings
from app.cpu_work_queue import CPU_WORK_QUEUE
from app.voice.language_config import SUPPORTED_LANGUAGES


class SHUSTTEngine:
    """Record speech from a microphone and transcribe it with Whisper."""

    def __init__(
        self,
        model_size: str | None = None,
        device_index: int | None = None,
        sample_rate: int | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model_size = model_size or self.settings.stt_model_size
        self.device_index = (
            self.settings.microphone_device if device_index is None else device_index
        )
        self.sample_rate = sample_rate or self.settings.sample_rate
        self.model: WhisperModel | None = None

    def load_model(self) -> None:
        """Load the Whisper model once, on its first transcription."""
        with CPU_WORK_QUEUE.slot(timeout=self.settings.request_timeout_seconds):
            self._load_model_unlocked()

    def _load_model_unlocked(self) -> None:
        if self.model is None:
            print("SHU: Loading Speech Recognition Model...")
            self.model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
            )
            print("SHU: STT Model Ready!")

    def record_audio(
        self,
        duration: float = 5,
        *,
        stop_event: threading.Event | None = None,
        mute_event: threading.Event | None = None,
        on_started: Callable[[], None] | None = None,
    ) -> np.ndarray:
        """Record a mono float32 audio clip from the selected microphone."""
        if duration <= 0:
            raise ValueError("duration must be greater than zero")

        print("\nSHU is listening...")
        print("Speak now!")
        if stop_event is not None or mute_event is not None:
            blocksize = max(1, int(self.sample_rate * 0.1))
            max_samples = int(duration * self.sample_rate)
            captured = 0
            blocks: list[np.ndarray] = []
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                device=self.device_index,
                blocksize=blocksize,
            ) as stream:
                if on_started is not None:
                    on_started()
                while captured < max_samples:
                    if (stop_event is not None and stop_event.is_set()) or (
                        mute_event is not None and mute_event.is_set()
                    ):
                        break
                    frames = min(blocksize, max_samples - captured)
                    block, _ = stream.read(frames)
                    if (stop_event is not None and stop_event.is_set()) or (
                        mute_event is not None and mute_event.is_set()
                    ):
                        break
                    mono = np.asarray(block, dtype=np.float32).reshape(-1)
                    blocks.append(mono)
                    captured += len(mono)
            if (stop_event is not None and stop_event.is_set()) or (
                mute_event is not None and mute_event.is_set()
            ):
                return np.empty(0, dtype=np.float32)
            return np.concatenate(blocks) if blocks else np.empty(0, dtype=np.float32)

        audio = sd.rec(
            int(duration * self.sample_rate),
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device_index,
        )
        if on_started is not None:
            on_started()
        sd.wait()
        return np.squeeze(audio)

    def record_until_silence(
        self,
        *,
        max_duration: float = 15,
        silence_seconds: float = 1.0,
        threshold: float = 0.012,
        min_speech_seconds: float = 0.25,
        stop_event: threading.Event | None = None,
        mute_event: threading.Event | None = None,
        on_started: Callable[[], None] | None = None,
    ) -> np.ndarray:
        """Record a phrase until a short RMS-based silence interval is detected."""
        if max_duration <= 0 or silence_seconds <= 0 or min_speech_seconds < 0:
            raise ValueError("Recording durations must be positive")
        if threshold <= 0:
            raise ValueError("threshold must be positive")

        blocksize = max(1, int(self.sample_rate * 0.1))
        blocks: list[np.ndarray] = []
        speech_started = False
        silence_samples = 0
        max_samples = int(max_duration * self.sample_rate)

        print("\nSHU is listening... Speak now, then pause to finish.")
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device_index,
            blocksize=blocksize,
        ) as stream:
            if on_started is not None:
                on_started()
            captured = 0
            while captured < max_samples and not (
                stop_event is not None and stop_event.is_set()
            ) and not (mute_event is not None and mute_event.is_set()):
                frames = min(blocksize, max_samples - captured)
                block, _ = stream.read(frames)
                if (
                    (stop_event is not None and stop_event.is_set())
                    or (mute_event is not None and mute_event.is_set())
                ):
                    break
                mono = np.asarray(block, dtype=np.float32).reshape(-1)
                blocks.append(mono)
                captured += len(mono)

                rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
                if rms >= threshold:
                    speech_started = True
                    silence_samples = 0
                elif speech_started:
                    silence_samples += len(mono)

                elapsed = captured / self.sample_rate
                if (
                    speech_started
                    and elapsed >= min_speech_seconds
                    and silence_samples >= silence_seconds * self.sample_rate
                ):
                    break

        if not speech_started or (
            stop_event is not None and stop_event.is_set()
        ) or (
            mute_event is not None and mute_event.is_set()
        ):
            return np.empty(0, dtype=np.float32)
        return np.concatenate(blocks) if blocks else np.empty(0, dtype=np.float32)

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        *,
        stop_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Convert a recorded waveform into text in a selected language."""
        started = time.perf_counter()
        waveform = np.asarray(audio, dtype=np.float32).reshape(-1)
        if waveform.size == 0:
            return {
                "text": "",
                "language": None,
                "language_probability": 0.0,
                "audio_duration": 0.0,
                "processing_seconds": 0.0,
                "language_supported": False,
            }

        language_code = None
        if language:
            normalized = language.strip().lower()
            language_code = SUPPORTED_LANGUAGES.get(normalized)
            if language_code is None and normalized in SUPPORTED_LANGUAGES.values():
                language_code = normalized
            if language_code is None:
                supported = ", ".join(SUPPORTED_LANGUAGES)
                raise ValueError(
                    f"Unsupported language '{language}'. Choose one of: {supported}."
                )

        with CPU_WORK_QUEUE.slot(
            timeout=self.settings.request_timeout_seconds,
            cancel_event=stop_event,
        ):
            self._load_model_unlocked()
            assert self.model is not None
            segments, info = self.model.transcribe(
                waveform,
                language=language_code,
                beam_size=5,
                vad_filter=False,
            )
            text = " ".join(segment.text.strip() for segment in segments)
            detected_language = getattr(info, "language", None)
            probability = float(getattr(info, "language_probability", 0.0) or 0.0)
        return {
            "text": text,
            "language": detected_language,
            "language_probability": probability,
            "audio_duration": waveform.size / self.sample_rate,
            "processing_seconds": time.perf_counter() - started,
            "language_supported": detected_language in SUPPORTED_LANGUAGES.values(),
        }

    def listen_and_transcribe(
        self,
        duration: float = 5,
        language: str | None = None,
        *,
        dynamic: bool = False,
        stop_event: threading.Event | None = None,
        mute_event: threading.Event | None = None,
        on_activity: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Record speech and transcribe it in the selected or detected language."""
        if (stop_event is not None and stop_event.is_set()) or (
            mute_event is not None and mute_event.is_set()
        ):
            return self.transcribe(np.empty(0, dtype=np.float32), language=language)
        capture_options = {}
        if on_activity is not None:
            capture_options["on_started"] = lambda: on_activity("recording")
        audio = (
            self.record_until_silence(
                max_duration=duration,
                stop_event=stop_event,
                mute_event=mute_event,
                **capture_options,
            )
            if dynamic
            else self.record_audio(
                duration,
                stop_event=stop_event,
                mute_event=mute_event,
                **capture_options,
            )
        )
        if (stop_event is not None and stop_event.is_set()) or (
            mute_event is not None and mute_event.is_set()
        ):
            audio = np.empty(0, dtype=np.float32)
        if on_activity is not None:
            on_activity("transcribing")
        print("\nSHU: Processing your voice...")
        result = self.transcribe(audio, language=language, stop_event=stop_event)
        print("\nRecognized Text:", result["text"])
        print("Detected Language:", result["language"])
        return result
