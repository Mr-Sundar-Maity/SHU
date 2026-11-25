import asyncio
import threading
from pathlib import Path
from unittest.mock import Mock

import numpy as np

from app.config import Settings
from app.voice.barge_in import BargeInCapture
from app.voice.tts_engine import SHUTTSEngine
from app.voice.voice_assistant import GOODBYES, GREETINGS, SHUVoiceAssistant


class _FakeInputStream:
    def __init__(self, blocks):
        self.blocks = iter(blocks)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, frames):
        block = next(self.blocks, 0.0)
        return np.full((frames, 1), block, dtype=np.float32), False


def test_barge_in_capture_keeps_preroll_and_stops_after_silence():
    monitor = BargeInCapture(
        device_index=1,
        sample_rate=8_000,
        rms_threshold=0.1,
        stream_factory=lambda **_kwargs: _FakeInputStream(
            [0.0, 0.2, 0.2, 0.3, 0.0]
        ),
        block_seconds=0.1,
        pre_roll_seconds=0.3,
        silence_seconds=0.1,
        max_duration=1.0,
        trigger_blocks=2,
    )

    assert monitor.start()
    assert monitor._finished_event.wait(1.0)
    audio = monitor.audio()
    monitor.stop()

    assert monitor.triggered
    assert audio is not None
    assert audio.size == 5 * 800
    assert np.all(audio[:800] == 0.0)
    assert np.all(audio[800:2400] == 0.2)
    assert np.all(audio[2400:3200] == 0.3)


def test_barge_in_capture_stays_off_while_microphone_is_muted():
    mute_event = threading.Event()
    mute_event.set()
    stream_factory = Mock()
    monitor = BargeInCapture(
        device_index=1,
        sample_rate=8_000,
        mute_event=mute_event,
        stream_factory=stream_factory,
    )

    assert monitor.start() is False
    assert monitor.finished
    assert not monitor.triggered
    assert monitor.audio() is None
    stream_factory.assert_not_called()


def test_barge_in_capture_can_use_the_system_default_microphone():
    monitor = BargeInCapture(
        device_index=None,
        sample_rate=8_000,
        stream_factory=lambda **kwargs: (
            _FakeInputStream([0.0])
            if kwargs["device"] is None
            else _FakeInputStream([0.2])
        ),
    )

    assert monitor.start()
    monitor.stop()

    assert not monitor.triggered


def test_tts_stops_for_barge_in_and_returns_the_buffer_to_stt(monkeypatch, tmp_path):
    from app.voice import tts_engine

    audio = np.ones(1_600, dtype=np.float32)

    class FakeBargeIn:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.stopped = False

        def start(self):
            return True

        @property
        def triggered(self):
            return True

        @property
        def finished(self):
            return True

        @property
        def error(self):
            return None

        def stop(self):
            self.stopped = True

        def audio(self):
            return audio.copy()

    monitors = []

    def create_monitor(**kwargs):
        monitor = FakeBargeIn(**kwargs)
        monitors.append(monitor)
        return monitor

    async def fake_generate(_text, output_file):
        Path(output_file).write_bytes(b"synthetic audio")

    settings = Settings.from_env({"SHU_VOICE_BARGE_IN": "true"})
    engine = SHUTTSEngine(
        language="en", settings=settings, barge_in_factory=create_monitor
    )
    monkeypatch.setattr(engine, "generate_audio", fake_generate)
    monkeypatch.setattr(tts_engine.pygame.mixer, "get_init", lambda: True)
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "load", Mock())
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "set_volume", Mock())
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "play", Mock())
    music_stop = Mock()
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "stop", music_stop)
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "get_busy", lambda: True)
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "unload", Mock())

    assert asyncio.run(engine.speak_async("A harmless interruption test"))

    music_stop.assert_called_once()
    assert monitors[0].stopped
    np.testing.assert_array_equal(engine.take_interrupted_audio(), audio)
    assert engine.take_interrupted_audio() is None


def test_tts_keeps_playing_when_barge_in_microphone_is_unavailable(
    monkeypatch, tmp_path
):
    from app.voice import tts_engine

    class UnavailableBargeIn:
        error = OSError("synthetic microphone failure")

        def __init__(self, **_kwargs):
            self.stopped = False

        def start(self):
            return False

        def stop(self):
            self.stopped = True

    monitors = []

    def create_monitor(**kwargs):
        monitor = UnavailableBargeIn(**kwargs)
        monitors.append(monitor)
        return monitor

    async def fake_generate(_text, output_file):
        Path(output_file).write_bytes(b"synthetic audio")

    settings = Settings.from_env(
        {"SHU_VOICE_BARGE_IN": "true", "SHU_TTS_VOLUME": "0.65"}
    )
    engine = SHUTTSEngine(
        language="en", settings=settings, barge_in_factory=create_monitor
    )
    monkeypatch.setattr(engine, "generate_audio", fake_generate)
    monkeypatch.setattr(tts_engine.pygame.mixer, "get_init", lambda: True)
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "load", Mock())
    music_set_volume = Mock()
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "set_volume", music_set_volume)
    music_play = Mock()
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "play", music_play)
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "get_busy", lambda: False)
    monkeypatch.setattr(tts_engine.pygame.mixer.music, "unload", Mock())

    assert asyncio.run(engine.speak_async("A harmless fallback test"))

    music_play.assert_called_once()
    music_set_volume.assert_called_once_with(0.65)
    assert monitors[0].stopped
    assert engine.take_interrupted_audio() is None


def test_assistant_transcribes_interrupted_audio_before_opening_a_new_recording():
    audio = np.ones(1_600, dtype=np.float32)

    class FakeSTT:
        def __init__(self):
            self.transcribed = []
            self.record_calls = 0

        def transcribe(self, samples, *, language=None, stop_event=None):
            self.transcribed.append((samples, language))
            return {
                "text": "stop",
                "language": "en",
                "language_probability": 0.99,
            }

        def listen_and_transcribe(self, **_kwargs):
            self.record_calls += 1
            raise AssertionError("Interrupted audio should be transcribed first")

    class FakeTTS:
        def __init__(self):
            self.spoken = []
            self._audio = audio.copy()
            self.mute_event = None

        def set_language(self, _language):
            pass

        def set_mute_event(self, event):
            self.mute_event = event

        def speak(self, text):
            self.spoken.append(text)
            return True

        def take_interrupted_audio(self):
            captured = self._audio
            self._audio = None
            return captured

        def stop(self):
            pass

    class FakeAI:
        def ask(self, *_args, **_kwargs):
            raise AssertionError("The stop phrase must exit before AI")

    settings = Settings.from_env(
        {"SHU_DEFAULT_LANGUAGE": "en", "SHU_MICROPHONE_DEVICE": ""}
    )
    stt = FakeSTT()
    tts = FakeTTS()
    assistant = SHUVoiceAssistant(settings=settings, stt=stt, tts=tts, ai=FakeAI())
    assistant.start(max_turns=1)

    assert len(stt.transcribed) == 1
    np.testing.assert_array_equal(stt.transcribed[0][0], audio)
    assert stt.transcribed[0][1] is None
    assert stt.record_calls == 0
    assert tts.mute_event is assistant._mute_event
    assert tts.spoken == [GREETINGS["en"], GOODBYES["en"]]
