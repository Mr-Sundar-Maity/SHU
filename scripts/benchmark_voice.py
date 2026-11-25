"""Measure a consented WAV through local SHU voice processing to a silent sink."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.ai_engine import SHUAIEngine
from app.config import Settings, get_settings
from app.cpu_work_queue import CPU_WORK_QUEUE
from app.voice.language_config import SUPPORTED_LANGUAGES
from app.voice.stt_engine import SHUSTTEngine
from app.voice.voice_assistant import SHUVoiceAssistant
from scripts.benchmark_local_ai import _percentile, system_memory_snapshot
from scripts.evaluate_stt import SAMPLE_RATE, read_audio

_MAX_TRIALS = 20
_MAX_REQUEST_SECONDS = 30.0
_MIN_AVAILABLE_BYTES = 2 * 1024**3


def _loopback_base_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname
    if (
        parts.scheme not in {"http", "https"}
        or host not in {"localhost", "127.0.0.1", "::1"}
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Voice benchmark requires a loopback Ollama endpoint.")
    # Use a numeric address so that resolving the hostname cannot leave loopback.
    address = "[::1]" if host == "::1" else "127.0.0.1"
    port = f":{parts.port}" if parts.port is not None else ""
    return urlunsplit((parts.scheme, address + port, parts.path.rstrip("/"), "", ""))


class _FileInput:
    def __init__(self, audio: Path, engine: SHUSTTEngine) -> None:
        self.audio = audio
        self.engine = engine
        self.used = False
        self.interrupted = False
        self.started: float | None = None
        self.file_read_seconds: float | None = None
        self.whisper_seconds: float | None = None

    def listen_and_transcribe(self, *, language, stop_event, **_):
        if self.used:
            raise InterruptedError("Each trial has one input clip.")
        self.used = True
        self.started = time.perf_counter()
        try:
            waveform = read_audio(self.audio)
            read_finished = time.perf_counter()
            self.file_read_seconds = read_finished - self.started
            result = self.engine.transcribe(waveform, language=language, stop_event=stop_event)
        except KeyboardInterrupt:
            self.interrupted = True
            raise
        self.whisper_seconds = time.perf_counter() - read_finished
        return result


class _LocalAI:
    def __init__(self, settings: Settings, session: requests.Session) -> None:
        self.settings = settings
        self.session = session
        self.seconds: float | None = None

    def require_local_model(self) -> None:
        response = self.session.get(
            f"{self.settings.local_ai_base_url}/api/tags",
            timeout=min(5.0, self.settings.request_timeout_seconds),
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise RuntimeError("Ollama model inventory unavailable.")
        data = response.json()
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            raise RuntimeError("Ollama model inventory is invalid.")
        selected = self.settings.local_ai_model.casefold()
        if ":" not in selected.rsplit("/", 1)[-1]:
            selected += ":latest"
        if selected.endswith((":cloud", "-cloud")):
            raise ValueError("Voice benchmark requires a downloaded local Ollama model.")
        for model in models:
            if not isinstance(model, dict) or not any(
                isinstance(model.get(key), str) and model[key].casefold() == selected
                for key in ("model", "name")
            ):
                continue
            if model.get("remote_host") or model.get("remote_model"):
                break
            details = model.get("details")
            if isinstance(details, dict) and details.get("format") in {"gguf", "safetensors"}:
                return
            break
        raise ValueError("Voice benchmark requires a downloaded local Ollama model.")

    def ask(
        self,
        prompt: str,
        *,
        provider: str,
        context: Sequence[Mapping[str, str]],
        system_instruction: str,
        sensitive: bool,
    ) -> str:
        if provider != "ollama":
            raise ValueError("Voice benchmark permits only Ollama.")
        started = time.perf_counter()
        self.seconds = None
        with CPU_WORK_QUEUE.slot(timeout=self.settings.request_timeout_seconds):
            response = self.session.post(
                f"{self.settings.local_ai_base_url}/api/chat",
                json={
                    "model": self.settings.local_ai_model,
                    "messages": SHUAIEngine._messages(
                        prompt, context, system_instruction=system_instruction
                    ),
                    "stream": False,
                },
                timeout=self.settings.request_timeout_seconds,
                allow_redirects=False,
            )
            if response.status_code != 200:
                raise RuntimeError("Ollama did not complete the local request.")
            data = response.json()
            message = data.get("message") if isinstance(data, dict) else None
            answer = message.get("content") if isinstance(message, dict) else None
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("Ollama returned no reply.")
        self.seconds = time.perf_counter() - started
        return answer.strip()


class _SpeechSink:
    def __init__(self) -> None:
        self.reply_ready = False
        self.handoff: float | None = None

    def set_language(self, _language: str) -> None:
        pass

    def on_turn(self, _question: str, _answer: str) -> None:
        self.reply_ready = True

    def speak(self, _text: str) -> bool:
        if self.reply_ready:
            self.handoff = time.perf_counter()
        return True


def _cached_whisper(settings: Settings) -> SHUSTTEngine:
    from faster_whisper.utils import download_model

    path = download_model(settings.stt_model_size, local_files_only=True)
    return SHUSTTEngine(model_size=path, sample_rate=SAMPLE_RATE, settings=settings)


def _trial(
    audio: Path, whisper: SHUSTTEngine, ai: _LocalAI, language: str | None
) -> dict[str, float] | None:
    source = _FileInput(audio, whisper)
    sink = _SpeechSink()
    assistant = SHUVoiceAssistant(
        settings=ai.settings, stt=source, ai=ai, tts=sink, on_turn=sink.on_turn
    )
    try:
        assistant.start(max_turns=1, language=language)
    except (OSError, RuntimeError, ValueError, requests.RequestException):
        return None
    if source.interrupted:
        raise KeyboardInterrupt
    if (
        sink.handoff is None or source.started is None or source.file_read_seconds is None
        or source.whisper_seconds is None or ai.seconds is None
    ):
        return None
    return {
        "file_read": source.file_read_seconds,
        "whisper": source.whisper_seconds,
        "ollama": ai.seconds,
        "file_to_speech_handoff": sink.handoff - source.started,
    }


def _timings(samples: list[dict[str, float]]) -> dict[str, dict[str, float | int | None]]:
    result = {}
    for stage in ("file_read", "whisper", "ollama", "file_to_speech_handoff"):
        milliseconds = [sample[stage] * 1000 for sample in samples]
        result[stage] = {
            "samples": len(milliseconds),
            "median_ms": round(statistics.median(milliseconds), 3) if milliseconds else None,
            "p95_ms": _percentile(milliseconds, 95),
        }
    return result


def benchmark(audio: Path, *, trials: int = 5, language: str | None = None) -> dict:
    """Run bounded voice turns using a file that the speaker agreed to use."""
    if not 1 <= trials <= _MAX_TRIALS:
        raise ValueError(f"Trials must be from 1 to {_MAX_TRIALS}.")
    if audio.suffix.casefold() != ".wav" or str(audio).startswith(("\\\\", "//")):
        raise ValueError("Voice benchmark requires a local mono 16 kHz WAV file.")
    settings = get_settings()
    endpoint = _loopback_base_url(settings.local_ai_base_url)
    successes = []
    later_successes = []
    attempted = 0
    stop_reason = "trials_complete"
    with (
        tempfile.TemporaryDirectory(prefix="shu-voice-benchmark-") as private_dir,
        requests.Session() as session,
        open(os.devnull, "w", encoding="utf-8") as silent,
        redirect_stdout(silent),
        redirect_stderr(silent),
    ):
        isolated = replace(
            settings,
            data_dir=Path(private_dir),
            local_ai_base_url=endpoint,
            ai_provider="ollama",
            cloud_ai_enabled=False,
            cloud_fallback=False,
            local_fallback=False,
            allow_cloud_personal_data=False,
            gemini_api_key=None,
            wakeword_model_path=None,
            voice_barge_in=False,
            request_timeout_seconds=min(settings.request_timeout_seconds, _MAX_REQUEST_SECONDS),
        )
        session.trust_env = False
        ai = _LocalAI(isolated, session)
        ai.require_local_model()
        whisper = _cached_whisper(isolated)
        for index in range(trials):
            memory = system_memory_snapshot()
            if memory is not None and memory["available_physical_bytes"] < _MIN_AVAILABLE_BYTES:
                stop_reason = "available_memory_below_safety_floor"
                break
            attempted += 1
            result = _trial(audio, whisper, ai, language)
            if result is not None:
                successes.append(result)
                if index > 0:
                    later_successes.append(result)
    return {
        "whisper_model": settings.stt_model_size,
        "ollama_model": settings.local_ai_model,
        "language_mode": language or "auto",
        "input": "consented WAV file",
        "output": "silent speech handoff",
        "requested_trials": trials,
        "attempted_trials": attempted,
        "successful_trials": len(successes),
        "failed_trials": attempted - len(successes),
        "stop_reason": stop_reason,
        "all_successful": _timings(successes),
        "after_first_trial": _timings(later_successes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="local mono 16 kHz WAV, at most 30 seconds")
    parser.add_argument("--consented", action="store_true", help="the speaker agreed to use this file")
    parser.add_argument("--trials", type=int, default=5, choices=range(1, _MAX_TRIALS + 1))
    parser.add_argument("--language", choices=sorted(SUPPORTED_LANGUAGES.values()), help="force a language code")
    args = parser.parse_args(argv)
    if not args.consented:
        parser.error("Use --consented only with a recording approved for this benchmark.")
    try:
        result = benchmark(args.audio, trials=args.trials, language=args.language)
    except KeyboardInterrupt:
        print("Voice benchmark stopped.", file=sys.stderr)
        return 130
    except Exception as error:
        print(
            f"Voice benchmark failed ({type(error).__name__}). Check the local Ollama model and Whisper cache.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["successful_trials"] == args.trials else 1


if __name__ == "__main__":
    raise SystemExit(main())
