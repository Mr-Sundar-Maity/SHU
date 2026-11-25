"""Measure SHU transcription against a local corpus and emit aggregate metrics."""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from collections.abc import Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.voice.language_config import MIN_LANGUAGE_CONFIDENCE, SUPPORTED_LANGUAGES

SAMPLE_RATE = 16_000
LANGUAGES = frozenset(SUPPORTED_LANGUAGES.values())
COHORTS = {"clean", "noisy", "code-switch"}
MAX_AUDIO_FRAMES = 30 * SAMPLE_RATE


@dataclass(frozen=True)
class Sample:
    audio: Path
    language: str
    cohort: str
    reference: tuple[str, ...]


def normalized_words(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(
        "".join(
            char if category[0] in "LMN" else " "
            for char in normalized
            if (category := unicodedata.category(char)) != "Cf"
        ).split()
    )


def edit_distance(reference: Sequence[str], prediction: Sequence[str]) -> int:
    """Count insertions, deletions, and substitutions with one row of storage."""
    if len(prediction) > len(reference):
        reference, prediction = prediction, reference
    previous = list(range(len(prediction) + 1))
    for index, expected in enumerate(reference, 1):
        current = [index]
        for column, observed in enumerate(prediction, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (expected != observed),
            ))
        previous = current
    return previous[-1]


def load_samples(manifest: Path) -> list[Sample]:
    with manifest.open("rb") as stream:
        raw = stream.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("Manifest exceeds 1 MiB")
    entries = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
        raise ValueError("Manifest must be a list of 1-500 samples")
    directory = manifest.resolve().parent
    samples = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"Sample {index} must be an object")
        filename = entry.get("audio")
        language = entry.get("language")
        cohort = entry.get("cohort", "clean")
        reference = entry.get("reference")
        if not isinstance(filename, str) or not filename:
            raise ValueError(f"Sample {index} needs a relative WAV file")
        relative = Path(filename)
        audio = (directory / relative).resolve()
        if (
            relative.is_absolute() or relative.anchor or ".." in relative.parts
            or relative.suffix.casefold() != ".wav" or not audio.is_relative_to(directory)
        ):
            raise ValueError(f"Sample {index} WAV must stay inside the corpus directory")
        if not isinstance(language, str) or language not in LANGUAGES:
            raise ValueError(f"Sample {index} must use a supported language code")
        if not isinstance(cohort, str) or cohort not in COHORTS:
            raise ValueError(f"Sample {index} has an unknown cohort")
        words = normalized_words(reference) if isinstance(reference, str) else ()
        if not words or len(reference) > 1000:
            raise ValueError(f"Sample {index} needs a reference of at most 1000 characters")
        samples.append(Sample(audio, language, cohort, words))
    return samples


def read_audio(path: Path):
    with sf.SoundFile(path) as clip:
        if (
            clip.format != "WAV" or clip.samplerate != SAMPLE_RATE
            or clip.channels != 1 or not 1 <= clip.frames <= MAX_AUDIO_FRAMES
        ):
            raise ValueError("Use mono 16 kHz WAV clips up to 30 seconds")
        return clip.read(MAX_AUDIO_FRAMES, dtype="float32")


@dataclass
class Metrics:
    samples: int = 0
    word_errors: int = 0
    words: int = 0
    character_errors: int = 0
    characters: int = 0
    language_matches: int = 0
    rejected_utterances: int = 0
    incorrect_languages_accepted: int = 0
    elapsed_seconds: float = 0.0

    def report(self, *, auto: bool) -> dict:
        result = {
            "samples": self.samples,
            "word_errors": self.word_errors,
            "reference_words": self.words,
            "wer": round(self.word_errors / self.words, 6),
            "character_errors": self.character_errors,
            "reference_characters": self.characters,
            "cer": round(self.character_errors / self.characters, 6),
            "transcription_seconds": round(self.elapsed_seconds, 3),
        }
        if auto:
            result.update(
                language_matches=self.language_matches,
                rejected_utterances=self.rejected_utterances,
                incorrect_languages_accepted=self.incorrect_languages_accepted,
            )
        return result


def evaluate(samples: list[Sample], engine, modes: tuple[str, ...]) -> dict:
    groups: dict[tuple[str, str, str], Metrics] = {}
    for index, sample in enumerate(samples, 1):
        try:
            audio = read_audio(sample.audio)
        except (OSError, RuntimeError, ValueError) as error:
            raise ValueError(f"Sample {index} must be a readable mono 16 kHz WAV up to 30 seconds") from error
        reference_chars = "".join(sample.reference)
        for mode in modes:
            started = time.perf_counter()
            forced_language = sample.language if mode == "forced" else None
            result = engine.transcribe(audio, language=forced_language)
            stats = groups.setdefault((sample.language, sample.cohort, mode), Metrics())
            stats.elapsed_seconds += time.perf_counter() - started
            predicted = normalized_words(result["text"])
            predicted_chars = "".join(predicted)
            stats.samples += 1
            stats.word_errors += edit_distance(sample.reference, predicted)
            stats.words += len(sample.reference)
            stats.character_errors += edit_distance(reference_chars, predicted_chars)
            stats.characters += len(reference_chars)
            if mode == "auto":
                detected = result["language"]
                correct = detected == sample.language
                accepted = (
                    bool(result["text"].strip()) and detected in LANGUAGES
                    and result["language_probability"] >= MIN_LANGUAGE_CONFIDENCE
                )
                stats.language_matches += correct
                stats.rejected_utterances += not accepted
                stats.incorrect_languages_accepted += accepted and not correct
    return {
        "sample_count": len(samples),
        "missing_languages": sorted(LANGUAGES.difference(sample.language for sample in samples)),
        "results": [
            {"language": language, "cohort": cohort, "mode": mode, **stats.report(auto=mode == "auto")}
            for (language, cohort, mode), stats in sorted(groups.items())
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON corpus manifest kept alongside consented WAV files")
    parser.add_argument("--mode", choices=("auto", "forced", "both"), default="both")
    args = parser.parse_args(argv)
    try:
        samples = load_samples(args.manifest)
    except (OSError, ValueError) as error:
        detail = str(error) if type(error) is ValueError else "Use a readable UTF-8 JSON manifest"
        print(f"Cannot read the corpus: {detail}", file=sys.stderr)
        return 2
    from faster_whisper.utils import download_model

    from app.config import get_settings
    from app.voice.stt_engine import SHUSTTEngine

    try:
        settings = get_settings()
        cached_model = download_model(settings.stt_model_size, local_files_only=True)
        engine = SHUSTTEngine(model_size=cached_model, sample_rate=SAMPLE_RATE, settings=settings)
        modes = ("auto", "forced") if args.mode == "both" else (args.mode,)
        with redirect_stdout(sys.stderr):
            engine.load_model()
            report = evaluate(samples, engine, modes)
    except ValueError as error:
        # Input validation emits only an ordinal. Do not dump provider errors or paths.
        detail = str(error) if str(error).startswith("Sample ") else type(error).__name__
        print(f"Evaluation failed: {detail}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Evaluation failed: {type(error).__name__}. Check the local Whisper cache.", file=sys.stderr)
        return 1
    print(json.dumps({"model": settings.stt_model_size, **report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
