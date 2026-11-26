"""Measure a local ONNX wake model against a consented, labelled WAV corpus."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from time import perf_counter, process_time

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.voice.wake_word import (
    WAKE_BLOCK_SAMPLES,
    WAKE_DEBOUNCE_SECONDS,
    WAKE_SAMPLE_RATE,
    WAKE_THRESHOLD,
    WakeActivationGate,
    load_wake_word_model,
)

_MAX_MANIFEST_BYTES = 1_048_576
_MAX_CLIPS = 500
_MAX_CLIP_SECONDS = 600
_MAX_CORPUS_SECONDS = 7_200
_MAX_DEADLINE_SECONDS = 1_800


class CorpusError(ValueError):
    """Input error safe to show without including paths or sample content."""


@dataclass(frozen=True)
class Clip:
    audio: Path
    activation_window: tuple[float, float] | None


def _local_path(path: Path) -> Path:
    expanded = path.expanduser()
    if PureWindowsPath(expanded).anchor.startswith("\\\\"):
        raise CorpusError("Choose a local model and corpus directory")
    resolved = expanded.resolve()
    if PureWindowsPath(resolved).anchor.startswith("\\\\"):
        raise CorpusError("Choose a local model and corpus directory")
    return resolved


def load_clips(manifest: Path) -> list[Clip]:
    manifest = _local_path(manifest)
    with manifest.open("rb") as stream:
        raw = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise CorpusError("Manifest exceeds 1 MiB")
    entries = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(entries, list) or not 1 <= len(entries) <= _MAX_CLIPS:
        raise CorpusError(f"Manifest must describe 1 to {_MAX_CLIPS} clips")

    clips = []
    reviewed_paths: set[Path] = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise CorpusError(f"Clip {index} must be an object")
        filename = entry.get("audio")
        if not isinstance(filename, str) or not filename:
            raise CorpusError(f"Clip {index} needs a relative WAV path")
        relative = Path(filename)
        windows_path = PureWindowsPath(filename)
        if (
            relative.anchor or windows_path.anchor
            or ".." in relative.parts or ".." in windows_path.parts
            or ":" in filename or relative.suffix.casefold() != ".wav"
        ):
            raise CorpusError(f"Clip {index} WAV must stay inside the corpus directory")
        audio = _local_path(manifest.parent / relative)
        if not audio.is_relative_to(manifest.parent):
            raise CorpusError(f"Clip {index} WAV must stay inside the corpus directory")
        if audio in reviewed_paths:
            raise CorpusError(f"Clip {index} repeats an earlier WAV path")
        reviewed_paths.add(audio)

        window = entry.get("activation_window_seconds")
        label = entry.get("label")
        if label == "positive":
            if (
                not isinstance(window, list) or len(window) != 2
                or not all(type(value) in (int, float) and 0 <= value <= _MAX_CLIP_SECONDS for value in window)
                or window[0] >= window[1]
            ):
                raise CorpusError(f"Clip {index} needs a positive activation window [start, end] in seconds")
            clips.append(Clip(audio, (float(window[0]), float(window[1]))))
        elif label == "negative" and window is None:
            clips.append(Clip(audio, None))
        else:
            raise CorpusError(f"Clip {index} must have a positive or negative label; only positive clips have windows")
    return clips


def _require_time(deadline: float) -> None:
    if perf_counter() >= deadline:
        raise TimeoutError


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "p95": None}
    median, p95 = np.percentile(values, (50, 95))
    return {"median": float(median), "p95": float(p95)}


def evaluate(clips: list[Clip], model, *, deadline: float) -> dict:
    """Score first positive hits and full negative streams at live block size."""
    started, cpu_started = perf_counter(), process_time()
    block_times_ms: list[float] = []
    delays_ms: list[float] = []
    positives = misses = outside_window = negatives = false_hits = 0
    negative_frames = total_frames = ignored_tail_frames = 0

    for index, sample in enumerate(clips, 1):
        _require_time(deadline)
        try:
            audio = sf.SoundFile(sample.audio)
        except (OSError, RuntimeError, ValueError) as error:
            raise CorpusError(f"Clip {index} must be a readable WAV") from error
        with audio:
            blocks, tail = divmod(audio.frames, WAKE_BLOCK_SAMPLES)
            if (
                audio.format != "WAV" or audio.subtype != "PCM_16"
                or audio.samplerate != WAKE_SAMPLE_RATE or audio.channels != 1
                or blocks == 0 or audio.frames > _MAX_CLIP_SECONDS * WAKE_SAMPLE_RATE
            ):
                raise CorpusError(f"Clip {index} must be mono 16 kHz PCM-16 WAV, 80 ms to 10 minutes")
            clip_frames = blocks * WAKE_BLOCK_SAMPLES
            if total_frames + ignored_tail_frames + audio.frames > _MAX_CORPUS_SECONDS * WAKE_SAMPLE_RATE:
                raise CorpusError("Corpus exceeds 2 hours of audio")
            if sample.activation_window and sample.activation_window[1] > clip_frames / WAKE_SAMPLE_RATE:
                raise CorpusError(f"Clip {index} activation window must end within complete 80 ms blocks")
            total_frames += clip_frames
            ignored_tail_frames += tail
            model.reset()
            gate = WakeActivationGate()
            first_detection = None
            for block in range(1, blocks + 1):
                _require_time(deadline)
                frame = audio.read(WAKE_BLOCK_SAMPLES, dtype="int16")
                if len(frame) != WAKE_BLOCK_SAMPLES:
                    raise CorpusError(f"Clip {index} ended before its declared WAV duration")
                block_started = perf_counter()
                scores = model.predict(frame)
                block_times_ms.append((perf_counter() - block_started) * 1_000)
                audio_time = block * WAKE_BLOCK_SAMPLES / WAKE_SAMPLE_RATE
                if gate.should_activate(scores, audio_time):
                    if sample.activation_window is None:
                        false_hits += 1
                    elif first_detection is None:
                        first_detection = audio_time

            if sample.activation_window is None:
                negatives += 1
                negative_frames += clip_frames
            else:
                positives += 1
                low, high = sample.activation_window
                if first_detection is None:
                    misses += 1
                elif low <= first_detection <= high:
                    delays_ms.append((first_detection - low) * 1_000)
                else:
                    outside_window += 1

    _require_time(deadline)
    negative_seconds = negative_frames / WAKE_SAMPLE_RATE
    audio_seconds = total_frames / WAKE_SAMPLE_RATE
    cpu_seconds = process_time() - cpu_started
    return {
        "threshold": WAKE_THRESHOLD,
        "debounce_seconds": WAKE_DEBOUNCE_SECONDS,
        "audio_seconds": audio_seconds,
        "ignored_tail_seconds": ignored_tail_frames / WAKE_SAMPLE_RATE,
        "processed_blocks": len(block_times_ms),
        "evaluation_wall_seconds": perf_counter() - started,
        "evaluation_cpu_seconds": cpu_seconds,
        "cpu_seconds_per_audio_second": cpu_seconds / audio_seconds if audio_seconds else None,
        "prediction_ms_per_block": _summary(block_times_ms),
        "positive": {
            "clips": positives,
            "detected_in_window": len(delays_ms),
            "missed": misses,
            "first_detection_outside_window": outside_window,
            "detection_rate": len(delays_ms) / positives if positives else None,
            "delay_from_window_start_ms": _summary(delays_ms),
        },
        "negative": {
            "clips": negatives,
            "audio_seconds": negative_seconds,
            "false_activations": false_hits,
            "false_activations_per_hour": false_hits * 3600 / negative_seconds if negative_seconds else None,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            'Manifest is a JSON list with examples like {"audio":"speech.wav","label":"positive",'
            '"activation_window_seconds":[0.8,1.8]} or {"audio":"room.wav","label":"negative"}. '
            'Audio uses complete 80 ms blocks. Timing is offline; live microphone, mute and hardware accuracy need '
            'separate checks.'
        ),
    )
    parser.add_argument("model", type=Path, help="explicit local trained wake-word ONNX file")
    parser.add_argument("manifest", type=Path, help="labelled corpus JSON beside the WAV recordings")
    parser.add_argument("--consented", action="store_true", help="recordings are approved for evaluation")
    parser.add_argument(
        "--deadline-seconds", type=float, default=600,
        help="evaluation budget checked between blocks (1 to 1800 seconds, default 600)",
    )
    args = parser.parse_args(argv)
    if not args.consented:
        parser.error("Use --consented only with recordings approved for this evaluation")
    if not math.isfinite(args.deadline_seconds) or not 1 <= args.deadline_seconds <= _MAX_DEADLINE_SECONDS:
        parser.error("Evaluation budget must be from 1 to 1800 seconds")
    deadline = perf_counter() + args.deadline_seconds

    try:
        model_path = _local_path(args.model)
        if model_path.suffix.casefold() != ".onnx" or not model_path.is_file():
            raise CorpusError("Supply a local trained wake-word ONNX model")
        clips = load_clips(args.manifest)
        _require_time(deadline)
        load_started = perf_counter()
        model = load_wake_word_model(model_path)
        model_load_seconds = perf_counter() - load_started
        result = evaluate(clips, model, deadline=deadline)
    except CorpusError as error:
        print(error, file=sys.stderr)
        return 2
    except TimeoutError:
        print("Wake-word evaluation deadline exceeded before completion", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Wake-word evaluation failed ({type(error).__name__})", file=sys.stderr)
        return 1

    print(json.dumps({"model_load_seconds": model_load_seconds, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
