import json
from time import perf_counter

import numpy as np
import pytest
import soundfile as sf

from scripts import evaluate_wake_word as evaluator


class ScoreFromPCM:
    """Predict high on the marked synthetic blocks without loading a real model."""

    def __init__(self):
        self.clip_count = 0

    def reset(self):
        self.clip_count += 1

    def predict(self, frame):
        assert frame.dtype == np.int16
        assert frame.shape == (evaluator.WAKE_BLOCK_SAMPLES,)
        return {"fixture": 0.9 if frame[0] == 1 else 0.5}


def write_clip(path, block_values, *, tail=0, sample_rate=16_000):
    samples = np.repeat(np.array(block_values, dtype=np.int16), evaluator.WAKE_BLOCK_SAMPLES)
    samples = np.pad(samples, (0, tail))
    sf.write(path, samples, sample_rate, subtype="PCM_16")


def write_manifest(directory, entries):
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    return manifest


def test_evaluator_scores_first_positive_hits_and_debounced_false_rate(tmp_path):
    write_clip(tmp_path / "in-window.wav", [0, 1, 0])
    write_clip(tmp_path / "early-hit.wav", [1, 1, 1])
    write_clip(tmp_path / "miss.wav", [0, 0, 0])
    write_clip(tmp_path / "background.wav", [1] * 28, tail=60)
    manifest = write_manifest(tmp_path, [
        {"audio": filename, "label": "positive", "activation_window_seconds": [0.10, 0.23]}
        for filename in ("in-window.wav", "early-hit.wav", "miss.wav")
    ] + [{"audio": "background.wav", "label": "negative"}])
    model = ScoreFromPCM()

    result = evaluator.evaluate(evaluator.load_clips(manifest), model, deadline=perf_counter() + 10)

    assert model.clip_count == 4
    assert result["positive"]["detected_in_window"] == 1
    assert result["positive"]["first_detection_outside_window"] == 1
    assert result["positive"]["missed"] == 1
    assert result["positive"]["detection_rate"] == pytest.approx(1 / 3)
    assert result["positive"]["delay_from_window_start_ms"]["median"] == pytest.approx(60)
    assert result["negative"]["audio_seconds"] == pytest.approx(2.24)
    assert result["negative"]["false_activations"] == 2
    assert result["negative"]["false_activations_per_hour"] == pytest.approx(2 * 3600 / 2.24)
    assert result["ignored_tail_seconds"] == pytest.approx(60 / 16_000)
    assert result["processed_blocks"] == 37
    assert result["prediction_ms_per_block"]["p95"] >= 0
    assert result["cpu_seconds_per_audio_second"] >= 0


@pytest.mark.parametrize("audio", ["../out.wav", r"..\out.wav", r"\\server\share\out.wav", "C:out.wav"])
def test_manifest_rejects_outside_or_drive_relative_audio_paths(tmp_path, audio):
    manifest = write_manifest(tmp_path, [{"audio": audio, "label": "negative"}])
    with pytest.raises(evaluator.CorpusError, match="inside the corpus"):
        evaluator.load_clips(manifest)


def test_evaluator_rejects_nonconforming_wav_and_expired_deadline(tmp_path):
    audio = tmp_path / "audio.wav"
    write_clip(audio, [1], sample_rate=8_000)
    model = ScoreFromPCM()
    samples = [evaluator.Clip(audio, None)]
    with pytest.raises(evaluator.CorpusError, match="mono 16 kHz PCM-16"):
        evaluator.evaluate(samples, model, deadline=perf_counter() + 10)
    with pytest.raises(TimeoutError):
        evaluator.evaluate(samples, model, deadline=0)
    assert model.clip_count == 0


def test_cli_requires_consent_and_reports_without_paths(tmp_path, monkeypatch, capsys):
    model_path = tmp_path / "synthetic.onnx"
    model_path.write_bytes(b"fixture")
    write_clip(tmp_path / "audio.wav", [0, 0])
    manifest = write_manifest(tmp_path, [{"audio": "audio.wav", "label": "negative"}])
    loaded = []

    def load_model(path):
        loaded.append(path)
        return ScoreFromPCM()

    monkeypatch.setattr(evaluator, "load_wake_word_model", load_model)
    args = [str(model_path), str(manifest)]
    with pytest.raises(SystemExit) as error:
        evaluator.main(args)
    assert error.value.code == 2
    assert not loaded
    capsys.readouterr()

    assert evaluator.main(args + ["--consented"]) == 0
    result = capsys.readouterr()
    assert not result.err
    assert str(tmp_path) not in result.out
    metrics = json.loads(result.out)
    assert metrics["positive"]["detection_rate"] is None
    assert metrics["negative"]["false_activations_per_hour"] == 0
    assert metrics["model_load_seconds"] >= 0
    assert loaded == [model_path.resolve()]
