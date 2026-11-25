import numpy as np
import pytest

from app.voice.audio_diagnostics import analyze_input_audio, capture_input_level


def test_audio_level_report_flags_near_silence():
    report = analyze_input_audio(np.full(16_000, 0.00001, dtype=np.float32))

    assert report.sample_count == 16_000
    assert report.status == "silent"
    assert report.rms_dbfs < -90


def test_audio_level_report_flags_low_and_usable_signal():
    low = analyze_input_audio(np.full(16_000, 0.01, dtype=np.float32))
    usable = analyze_input_audio(np.full(16_000, 0.08, dtype=np.float32))

    assert low.status == "low"
    assert usable.status == "usable"
    assert usable.peak_dbfs > low.peak_dbfs


def test_audio_level_report_flags_clipping():
    audio = np.zeros(20_000, dtype=np.float32)
    audio[:20] = 1.0

    report = analyze_input_audio(audio)

    assert report.status == "clipping"
    assert report.clipping_fraction == pytest.approx(0.001)


@pytest.mark.parametrize("audio", [np.array([], dtype=np.float32), np.array([np.nan])])
def test_audio_level_report_rejects_empty_or_invalid_audio(audio):
    with pytest.raises(ValueError):
        analyze_input_audio(audio)


def test_capture_input_level_discards_audio_and_uses_selected_device(monkeypatch):
    captured = np.full((16_000, 1), 0.08, dtype=np.float32)
    calls = {}

    def record(frames, **kwargs):
        calls.update(frames=frames, **kwargs)
        return captured

    monkeypatch.setattr("app.voice.audio_diagnostics.sd.rec", record)
    monkeypatch.setattr("app.voice.audio_diagnostics.sd.wait", lambda: None)

    report = capture_input_level(7, duration_seconds=1.0, sample_rate=16_000)

    assert report.status == "usable"
    assert calls == {
        "frames": 16_000,
        "samplerate": 16_000,
        "channels": 1,
        "dtype": "float32",
        "device": 7,
    }


def test_capture_input_level_rejects_out_of_range_duration():
    with pytest.raises(ValueError, match="between 1 and 15"):
        capture_input_level(1, duration_seconds=0.5)
