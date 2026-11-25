import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile

from app.config import Settings
from scripts import benchmark_voice


@pytest.fixture
def local_path(tmp_path):
    audio = tmp_path / "private-clip.wav"
    soundfile.write(audio, np.zeros(1600, dtype=np.float32), 16000)
    return audio


@pytest.fixture
def capture_local(monkeypatch, tmp_path):
    settings = Settings.from_env({
        "SHU_AI_PROVIDER": "google",
        "SHU_CLOUD_FALLBACK": "true",
        "SHU_VOICE_BARGE_IN": "true",
        "SHU_WAKEWORD_MODEL_PATH": str(tmp_path / "unused-wake-file"),
        "SHU_DATA_DIR": str(tmp_path / "real-settings"),
        "LOCAL_AI_BASE_URL": "http://localhost:11434",
    })
    settings.database_path.parent.mkdir(parents=True)
    settings.database_path.write_text("synthetic private database")
    model = {
        "model": settings.local_ai_model,
        "details": {"format": "gguf"},
    }
    calls = SimpleNamespace(chat=[], stt=[], settings=settings, model=model)

    class Session:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, url, *, timeout, allow_redirects):
            assert not self.trust_env and not allow_redirects
            assert timeout == 5 and url == "http://127.0.0.1:11434/api/tags"
            return SimpleNamespace(status_code=200, json=lambda: {"models": [model]})

        def post(self, url, *, json, timeout, allow_redirects):
            assert not self.trust_env and not allow_redirects
            assert timeout == 30 and url == "http://127.0.0.1:11434/api/chat"
            calls.chat.append(json)
            print("synthetic response from internal implementation")
            return SimpleNamespace(
                status_code=calls.status_code,
                json=lambda: {"message": {"content": "private synthetic reply"}},
            )

    class STT:
        def transcribe(self, waveform, *, language, stop_event):
            assert waveform.size == 1600
            assert not stop_event.is_set()
            calls.stt.append(language)
            print("private synthetic transcript")
            return {
                "text": "private synthetic transcript",
                "language": "en",
                "language_probability": calls.confidence,
            }

    def cached_whisper(isolated):
        assert isolated.data_dir != settings.data_dir
        assert not isolated.database_path.exists()
        assert not isolated.cloud_ai_enabled and not isolated.cloud_fallback
        assert isolated.wakeword_model_path is None and not isolated.voice_barge_in
        assert isolated.ai_provider == "ollama"
        return STT()

    calls.confidence = 0.97
    calls.status_code = 200
    monkeypatch.setattr(benchmark_voice.requests, "Session", Session)
    monkeypatch.setattr(benchmark_voice, "get_settings", lambda: settings)
    monkeypatch.setattr(benchmark_voice, "system_memory_snapshot", lambda: None)
    monkeypatch.setattr(benchmark_voice, "_cached_whisper", cached_whisper)
    return calls


def test_benchmark_reports_separate_stage_latency_and_redacts_text(
    local_path, capture_local, monkeypatch, capsys,
):
    times = iter((0, .001, .401, .402, .702, .705, 1, 1.002, 1.502, 1.503, 1.703, 1.705))
    monkeypatch.setattr(benchmark_voice, "time", SimpleNamespace(perf_counter=lambda: next(times)))

    assert benchmark_voice.main([str(local_path), "--consented", "--trials", "2"]) == 0

    captured = capsys.readouterr()
    assert not captured.err
    assert "private" not in captured.out
    report = json.loads(captured.out)
    assert report["successful_trials"] == report["requested_trials"] == 2
    assert report["failed_trials"] == 0
    assert report["language_mode"] == "auto"
    assert report["all_successful"] == {
        "file_read": {"samples": 2, "median_ms": 1.5, "p95_ms": 1.95},
        "whisper": {"samples": 2, "median_ms": 450.0, "p95_ms": 495.0},
        "ollama": {"samples": 2, "median_ms": 250.0, "p95_ms": 295.0},
        "file_to_speech_handoff": {"samples": 2, "median_ms": 705.0, "p95_ms": 705.0},
    }
    assert report["after_first_trial"]["whisper"]["samples"] == 1
    assert capture_local.stt == [None, None]
    assert len(capture_local.chat) == 2
    for request in capture_local.chat:
        assert [message["role"] for message in request["messages"]] == ["system", "user"]
        assert request["messages"][-1]["content"] == "private synthetic transcript"
    assert capture_local.settings.database_path.read_text() == "synthetic private database"


def test_benchmark_rejects_non_loopback_before_network_or_audio(local_path, monkeypatch):
    settings = replace(Settings.from_env({}), local_ai_base_url="https://example.invalid")
    monkeypatch.setattr(benchmark_voice, "get_settings", lambda: settings)
    monkeypatch.setattr(benchmark_voice.requests, "Session", lambda: pytest.fail("network started"))

    with pytest.raises(ValueError, match="loopback"):
        benchmark_voice.benchmark(local_path, trials=1)


def test_benchmark_rejects_remote_model_stub_before_any_stt(local_path, capture_local):
    capture_local.model["remote_host"] = "https://example.invalid"

    with pytest.raises(ValueError, match="downloaded local"):
        benchmark_voice.benchmark(local_path, trials=1)

    assert capture_local.stt == capture_local.chat == []


def test_benchmark_bounds_rejected_utterance_to_one_input(local_path, capture_local):
    capture_local.confidence = 0.1

    report = benchmark_voice.benchmark(local_path, trials=1)

    assert report["successful_trials"] == 0 and report["failed_trials"] == 1
    assert report["all_successful"]["file_to_speech_handoff"]["median_ms"] is None
    assert capture_local.stt == [None]
    assert capture_local.chat == []


def test_benchmark_does_not_count_redirect_as_reply(local_path, capture_local, capsys):
    capture_local.status_code = 302

    assert benchmark_voice.main([str(local_path), "--consented", "--trials", "1", "--language", "en"]) == 1

    assert json.loads(capsys.readouterr().out)["failed_trials"] == 1
    assert capture_local.stt == ["en"]
    assert len(capture_local.chat) == 1


def test_benchmark_stops_before_inference_when_memory_is_low(local_path, capture_local, monkeypatch):
    monkeypatch.setattr(benchmark_voice, "system_memory_snapshot", lambda: {"available_physical_bytes": 100})

    report = benchmark_voice.benchmark(local_path, trials=2)

    assert report["attempted_trials"] == 0
    assert report["stop_reason"] == "available_memory_below_safety_floor"
    assert capture_local.stt == capture_local.chat == []


def test_benchmark_honors_interrupt_in_transcription(local_path, capture_local, monkeypatch, capsys):
    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        benchmark_voice, "_cached_whisper", lambda _settings: SimpleNamespace(transcribe=interrupted)
    )

    assert benchmark_voice.main([str(local_path), "--consented"]) == 130
    assert capture_local.chat == []
    assert capsys.readouterr().err == "Voice benchmark stopped.\n"
