import json
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from scripts.evaluate_stt import edit_distance, evaluate, load_samples, main, normalized_words


def test_edit_counts_and_normalization_preserve_indic_marks():
    assert normalized_words(" Ａ café\u0301! বাংলা। தமிழ் ") == (
        "a", "café\u0301", "বাংলা", "தமிழ்"
    )
    assert edit_distance(("a", "b", "c"), ("a", "x")) == 2
    assert edit_distance("தமிழ்", "") == len("தமிழ்")
    assert edit_distance("a", "abc") == 2


def write_corpus(directory, entries, *, sample_rate=16000):
    sf.write(directory / "test.wav", np.zeros(80, dtype=np.float32), sample_rate)
    manifest = directory / "corpus.json"
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    return manifest


def test_aggregate_uses_reference_lengths_and_voice_acceptance_rule(tmp_path):
    manifest = write_corpus(tmp_path, [
        {"audio": "test.wav", "language": "en", "reference": "one"},
        {"audio": "test.wav", "language": "en", "reference": "two three four"},
        {"audio": "test.wav", "language": "bn", "reference": "বাংলা test", "cohort": "code-switch"},
    ])
    settings = iter([
        ("replacement", "hi", 0.8), ("one", "en", 1.0),
        ("Two three four!", "en", 0.1), ("two three four", "en", 1.0),
        ("বাংলা test", "bn", 0.9), ("বাংলা test", "bn", 1.0),
    ])
    calls = []

    def transcribe(audio, *, language):
        assert audio.dtype == np.float32 and audio.shape == (80,)
        calls.append(language)
        text, detected, probability = next(settings)
        return {"text": text, "language": detected, "language_probability": probability}

    report = evaluate(load_samples(manifest), SimpleNamespace(transcribe=transcribe), ("auto", "forced"))
    results = {(row["language"], row["cohort"], row["mode"]): row for row in report["results"]}
    auto = results["en", "clean", "auto"]
    assert auto["samples"] == 2
    assert auto["word_errors"] == 1 and auto["reference_words"] == 4
    assert auto["wer"] == 0.25
    assert auto["cer"] > 0
    assert auto["language_matches"] == 1
    assert auto["rejected_utterances"] == 1
    assert auto["incorrect_languages_accepted"] == 1
    assert results["bn", "code-switch", "forced"]["wer"] == 0.0
    assert "language_matches" not in results["bn", "code-switch", "forced"]
    assert report["missing_languages"] == ["hi", "ml", "ta", "te"]
    assert calls == [None, "en", None, "en", None, "bn"]


@pytest.mark.parametrize("filename", ["../elsewhere.wav", "//outside.invalid/share/clip.wav", "image.png"])
def test_manifest_rejects_unsupported_or_external_audio(tmp_path, filename, monkeypatch):
    manifest = write_corpus(tmp_path, [
        {"audio": filename, "language": "bn", "reference": "বাংলা"},
    ])
    path_type = type(manifest)
    resolve = path_type.resolve

    def resolve_manifest_only(path):
        assert path == manifest
        return resolve(path)

    monkeypatch.setattr(path_type, "resolve", resolve_manifest_only)
    with pytest.raises(ValueError, match="Sample 1 WAV must stay"):
        load_samples(manifest)


def test_evaluation_requires_mono_16khz_wav(tmp_path):
    manifest = write_corpus(tmp_path, [
        {"audio": "test.wav", "language": "en", "reference": "test"},
    ], sample_rate=8000)
    with pytest.raises(ValueError, match="Sample 1 must be a readable mono 16 kHz WAV"):
        evaluate(load_samples(manifest), None, ("auto",))


def test_cli_uses_offline_cache_and_omits_sensitive_input(tmp_path, monkeypatch, capsys):
    from faster_whisper import utils

    from app import config
    from app.voice import stt_engine

    manifest = write_corpus(tmp_path, [
        {"audio": "test.wav", "language": "en", "reference": "fixture reference"},
    ])
    calls = []

    def cached_only(model, *, local_files_only):
        calls.append((model, local_files_only))
        return "cached-model"

    class Engine:
        def __init__(self, *, model_size, sample_rate, settings):
            assert model_size == "cached-model" and sample_rate == 16000

        def load_model(self):
            print("Loading model")

        def transcribe(self, _audio, *, language):
            assert language == "en"
            return {"text": "fixture prediction"}

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(stt_model_size="small"))
    monkeypatch.setattr(utils, "download_model", cached_only)
    monkeypatch.setattr(stt_engine, "SHUSTTEngine", Engine)
    assert main([str(manifest), "--mode", "forced"]) == 0
    output = capsys.readouterr()
    assert calls == [("small", True)]
    assert json.loads(output.out)["results"][0]["wer"] == 0.5
    assert "fixture" not in output.out + output.err
    assert "test.wav" not in output.out + output.err
