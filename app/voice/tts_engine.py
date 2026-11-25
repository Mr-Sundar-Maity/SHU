"""Multilingual Edge TTS generation and serialized pygame playback."""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import uuid
from pathlib import Path

import edge_tts
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

from app.config import Settings, get_settings
from app.security.privacy import is_sensitive_text
from app.voice.barge_in import BargeInCapture


MALE_VOICES: dict[str, str] = {
    "bn": "bn-IN-BashkarNeural",
    "hi": "hi-IN-MadhurNeural",
    "en": "en-US-GuyNeural",
    "ta": "ta-IN-ValluvarNeural",
    "te": "te-IN-MohanNeural",
    "ml": "ml-IN-MidhunNeural",
}


class SHUTTSEngine:
    """Generate and play speech; call ``stop`` to interrupt playback."""

    def __init__(
        self,
        voice: str | None = None,
        *,
        language: str | None = None,
        settings: Settings | None = None,
        barge_in_factory=None,
    ) -> None:
        self.settings = settings or get_settings()
        self.language = (language or self.settings.default_language).lower()
        self.voice = voice or MALE_VOICES.get(self.language, MALE_VOICES["en"])
        self.initialized = False
        self._playback_lock = asyncio.Lock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._mute_event = threading.Event()
        self._barge_in_factory = barge_in_factory or BargeInCapture
        self._interrupted_audio = None

    async def generate_audio(self, text: str, output_file: str | Path) -> None:
        if not text or not text.strip():
            raise ValueError("TTS text cannot be empty")
        if is_sensitive_text(text):
            raise PermissionError("Sensitive text is blocked from cloud speech generation")
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=f"{self.settings.tts_rate_percent:+d}%",
            volume="+0%",
        )
        output_path = Path(output_file)
        partial_path = output_path.with_name(
            f".{output_path.name}.{uuid.uuid4().hex}.part"
        )
        try:
            await asyncio.wait_for(
                communicate.save(str(partial_path)),
                timeout=self.settings.tts_timeout_seconds,
            )
            if not partial_path.is_file() or partial_path.stat().st_size == 0:
                raise RuntimeError("Edge TTS returned no audio")
            os.replace(partial_path, output_path)
        except BaseException:
            try:
                partial_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    async def speak_async(self, text: str) -> bool:
        """Generate and play a response asynchronously; return success status."""
        if not text or not text.strip():
            return True

        async with self._playback_lock:
            self._stop_event.clear()
            self._interrupted_audio = None
            temp_path: Path | None = None
            barge_in = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as file:
                    temp_path = Path(file.name)
                print("SHU: Generating voice...")
                await self.generate_audio(text, temp_path)
                if self._stop_event.is_set():
                    return True
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                self.initialized = True
                pygame.mixer.music.load(str(temp_path))
                pygame.mixer.music.set_volume(self.settings.tts_volume)
                if self._stop_event.is_set():
                    return True
                if (
                    self.settings.voice_barge_in
                    and not self._mute_event.is_set()
                ):
                    try:
                        barge_in = self._barge_in_factory(
                            device_index=self.settings.microphone_device,
                            sample_rate=self.settings.sample_rate,
                            rms_threshold=self.settings.voice_barge_in_rms,
                            mute_event=self._mute_event,
                        )
                        if not barge_in.start():
                            if barge_in.error is not None:
                                print(
                                    "SHU: Voice interruption unavailable:",
                                    type(barge_in.error).__name__,
                                )
                            barge_in.stop()
                            barge_in = None
                    except Exception as error:
                        if barge_in is not None:
                            try:
                                barge_in.stop()
                            except Exception:
                                pass
                            barge_in = None
                        print(
                            "SHU: Voice interruption unavailable:",
                            type(error).__name__,
                        )
                pygame.mixer.music.play()
                if self._pause_event.is_set():
                    pygame.mixer.music.pause()
                if self._stop_event.is_set():
                    pygame.mixer.music.stop()
                    return True
                print("SHU: Speaking...")
                while not self._stop_event.is_set():
                    if self._stop_event.is_set():
                        pygame.mixer.music.stop()
                        break
                    if self._pause_event.is_set():
                        await asyncio.sleep(0.05)
                        continue
                    if not pygame.mixer.music.get_busy():
                        break
                    if barge_in is not None and barge_in.triggered:
                        pygame.mixer.music.stop()
                        break
                    await asyncio.sleep(0.05)
                if (
                    barge_in is not None
                    and barge_in.triggered
                    and not self._stop_event.is_set()
                ):
                    print("SHU: Listening...")
                    while not barge_in.finished and not self._stop_event.is_set():
                        await asyncio.sleep(0.05)
                pygame.mixer.music.unload()
                if not self._stop_event.is_set():
                    print("SHU: Finished speaking!")
                return True
            except Exception as error:
                print("SHU TTS Error:", type(error).__name__)
                return False
            finally:
                if barge_in is not None:
                    try:
                        barge_in.stop()
                    except Exception as error:
                        print(
                            "SHU: Voice interruption cleanup error:",
                            type(error).__name__,
                        )
                    if barge_in.error is not None:
                        print(
                            "SHU: Voice interruption unavailable:",
                            type(barge_in.error).__name__,
                        )
                    if (
                        barge_in.triggered
                        and not self._stop_event.is_set()
                        and not self._mute_event.is_set()
                    ):
                        self._interrupted_audio = barge_in.audio()
                try:
                    pygame.mixer.music.unload()
                except pygame.error:
                    pass
                if temp_path is not None:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass

    def speak(self, text: str) -> bool:
        """Synchronous CLI wrapper. Async applications should await speak_async."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.speak_async(text))
        raise RuntimeError("Use 'await speak_async(text)' inside an async event loop")

    def stop(self) -> None:
        """Cancel pending speech generation and stop active playback."""
        self._stop_event.set()
        self._pause_event.clear()
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()

    def pause(self) -> None:
        """Pause current playback and hold queued speech until resumed."""
        self._pause_event.set()
        if pygame.mixer.get_init():
            try:
                pygame.mixer.music.pause()
            except pygame.error:
                # Speech may still be generating or waiting for the playback lock.
                pass

    def resume(self) -> None:
        """Resume current playback and allow queued speech to continue."""
        self._pause_event.clear()
        if pygame.mixer.get_init():
            try:
                pygame.mixer.music.unpause()
            except pygame.error:
                # No audio may be loaded yet; a later queued utterance can proceed.
                pass

    def set_mute_event(self, mute_event: threading.Event) -> None:
        """Share the assistant's reversible microphone mute with the monitor."""
        self._mute_event = mute_event

    def take_interrupted_audio(self):
        """Return the captured barge-in phrase once, then discard it."""
        audio = self._interrupted_audio
        self._interrupted_audio = None
        return audio

    def set_language(self, language: str) -> None:
        """Select a verified voice for one of SHU's supported languages."""
        normalized = language.lower()
        if normalized not in MALE_VOICES:
            raise ValueError("Unsupported TTS language: " + language)
        self.language = normalized
        self.voice = MALE_VOICES[normalized]
