"""Measure local Ollama round-trip latency using fixed, non-sensitive prompts."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.ai_engine import SHUAIEngine
from app.config import get_settings
from app.cpu_work_queue import CPU_WORK_QUEUE
from app.system_metrics import (
    system_memory_snapshot,
    system_cpu_snapshot,
    cpu_percent as _cpu_percent,
)

_SOAK_MIN_AVAILABLE_MIB = 2_048


def ollama_model_disk_size(settings) -> int | None:
    """Return the selected local model's installed size from Ollama's tags API."""
    try:
        response = requests.get(
            f"{settings.local_ai_base_url}/api/tags",
            timeout=min(5.0, settings.request_timeout_seconds),
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError, TypeError):
        return None

    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return None
    selected = settings.local_ai_model.casefold()
    for item in models:
        if not isinstance(item, dict):
            continue
        names = (item.get("name"), item.get("model"))
        if not any(isinstance(name, str) and name.casefold() == selected for name in names):
            continue
        size = item.get("size")
        if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
            return size
    return None


def _duration_seconds(value: object) -> float | None:
    """Convert a non-negative Ollama nanosecond duration to seconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        numeric = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return round(numeric / 1_000_000_000, 6)


def ollama_chat(settings, prompt: str) -> tuple[str, dict[str, float | None]]:
    """Run a fixed prompt through local Ollama and return safe timing metadata."""
    with CPU_WORK_QUEUE.slot(timeout=settings.request_timeout_seconds):
        response = requests.post(
            f"{settings.local_ai_base_url}/api/chat",
            json={
                "model": settings.local_ai_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama returned an invalid chat response")
        return content.strip(), {
            "load_duration_seconds": _duration_seconds(data.get("load_duration")),
            "server_total_duration_seconds": _duration_seconds(data.get("total_duration")),
            "prompt_eval_duration_seconds": _duration_seconds(
                data.get("prompt_eval_duration")
            ),
            "eval_duration_seconds": _duration_seconds(data.get("eval_duration")),
        }


def data_volume_snapshot(data_dir: Path) -> dict[str, int] | None:
    """Measure the filesystem containing SHU data without creating directories."""
    candidate = Path(data_dir)
    try:
        while not candidate.exists() and candidate.parent != candidate:
            candidate = candidate.parent
        usage = shutil.disk_usage(candidate)
    except (OSError, TypeError, ValueError):
        return None
    return {"total_bytes": int(usage.total), "free_bytes": int(usage.free)}


def _disk_report(snapshots: list[dict[str, int]]) -> dict[str, object]:
    if not snapshots:
        return {
            "data_volume_scope": "filesystem containing SHU data directory",
            "data_volume_samples": 0,
            "data_volume_total_mib": None,
            "data_volume_free_mib_before": None,
            "data_volume_free_mib_min": None,
            "data_volume_free_mib_after": None,
        }
    mib = 1024 * 1024
    free = [item["free_bytes"] for item in snapshots]
    return {
        "data_volume_scope": "filesystem containing SHU data directory",
        "data_volume_samples": len(snapshots),
        "data_volume_total_mib": round(snapshots[0]["total_bytes"] / mib, 1),
        "data_volume_free_mib_before": round(free[0] / mib, 1),
        "data_volume_free_mib_min": round(min(free) / mib, 1),
        "data_volume_free_mib_after": round(free[-1] / mib, 1),
    }


def _ollama_timing_report(samples: list[dict[str, float | None]]) -> dict[str, object]:
    report: dict[str, object] = {"ollama_timing_samples": len(samples)}
    fields = (
        ("load_duration_seconds", "model_load_seconds"),
        ("server_total_duration_seconds", "server_total_seconds"),
        ("prompt_eval_duration_seconds", "prompt_eval_seconds"),
        ("eval_duration_seconds", "generation_seconds"),
    )
    for source, label in fields:
        values = [item[source] for item in samples if item[source] is not None]
        report[f"{label}_samples"] = values
        report[f"{label}_median"] = (
            round(statistics.median(values), 6) if values else None
        )
        report[f"{label}_max"] = round(max(values), 6) if values else None
    return report


def _cpu_report(samples: list[float]) -> dict[str, object]:
    return {
        "system_cpu_scope": "whole system during each request",
        "system_cpu_samples": len(samples),
        "system_cpu_percent_samples": [round(value, 1) for value in samples],
        "system_cpu_percent_median": (
            round(statistics.median(samples), 1) if samples else None
        ),
        "system_cpu_percent_peak": round(max(samples), 1) if samples else None,
    }


def _memory_report(snapshots: list[dict[str, int]]) -> dict[str, object]:
    if not snapshots:
        return {
            "system_memory_samples": 0,
            "system_total_physical_mb": None,
            "system_available_memory_mb_before": None,
            "system_available_memory_mb_min": None,
            "system_available_memory_mb_after": None,
            "system_memory_load_percent_peak": None,
        }

    mib = 1024 * 1024
    available = [item["available_physical_bytes"] for item in snapshots]
    return {
        "system_memory_samples": len(snapshots),
        "system_total_physical_mb": round(snapshots[0]["total_physical_bytes"] / mib, 1),
        "system_available_memory_mb_before": round(available[0] / mib, 1),
        "system_available_memory_mb_min": round(min(available) / mib, 1),
        "system_available_memory_mb_after": round(available[-1] / mib, 1),
        "system_memory_load_percent_peak": max(
            item["memory_load_percent"] for item in snapshots
        ),
    }


def _percentile(samples: list[float], percentile: float) -> float | None:
    """Return an inclusive, linearly interpolated percentile in seconds."""
    if not samples:
        return None
    if not 0.0 <= percentile <= 100.0:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(samples)
    rank = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)
    return round(value, 3)


def benchmark(samples: int = 3) -> dict[str, object]:
    if not 1 <= samples <= 100:
        raise ValueError("samples must be from 1 to 100")
    settings = get_settings()
    host = urlsplit(settings.local_ai_base_url).hostname
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Local AI benchmark only permits a loopback Ollama endpoint")

    engine = SHUAIEngine(settings)
    resident_before = engine.local_model_loaded()
    latencies: list[float] = []
    response_lengths: list[int] = []
    ollama_timings: list[dict[str, float | None]] = []
    memory_snapshots: list[dict[str, int]] = []
    disk_snapshots: list[dict[str, int]] = []
    cpu_percent_samples: list[float] = []
    model_disk_size = ollama_model_disk_size(settings)
    memory_before = system_memory_snapshot()
    if memory_before is not None:
        memory_snapshots.append(memory_before)
    disk_before = data_volume_snapshot(settings.data_dir)
    if disk_before is not None:
        disk_snapshots.append(disk_before)
    prompt = "Reply with exactly one word: READY"
    started_total = time.perf_counter()
    for _ in range(samples):
        started = time.perf_counter()
        cpu_before = system_cpu_snapshot()
        answer, timing = ollama_chat(settings, prompt)
        cpu_after = system_cpu_snapshot()
        cpu_percent = _cpu_percent(cpu_before, cpu_after)
        if cpu_percent is not None:
            cpu_percent_samples.append(cpu_percent)
        latencies.append(time.perf_counter() - started)
        response_lengths.append(len(answer))
        ollama_timings.append(timing)
        memory_after = system_memory_snapshot()
        if memory_after is not None:
            memory_snapshots.append(memory_after)
        disk_after = data_volume_snapshot(settings.data_dir)
        if disk_after is not None:
            disk_snapshots.append(disk_after)

    ordered = sorted(latencies)
    report: dict[str, object] = {
        "model": settings.local_ai_model,
        "model_disk_size_bytes": model_disk_size,
        "model_disk_size_mib": (
            round(model_disk_size / (1024 * 1024), 1)
            if model_disk_size is not None
            else None
        ),
        "samples": samples,
        "resident_before": resident_before,
        "resident_after": engine.local_model_loaded(),
        "sample_seconds": [round(value, 3) for value in latencies],
        "median_seconds": round(statistics.median(latencies), 3),
        "p95_seconds": _percentile(latencies, 95),
        "min_seconds": round(ordered[0], 3),
        "max_seconds": round(ordered[-1], 3),
        "total_seconds": round(time.perf_counter() - started_total, 3),
        "response_characters": response_lengths,
        "prompt_content": "fixed benign prompt; response text is not emitted",
    }
    report.update(_memory_report(memory_snapshots))
    report.update(_disk_report(disk_snapshots))
    report.update(_cpu_report(cpu_percent_samples))
    report.update(_ollama_timing_report(ollama_timings))
    return report


def soak(
    duration_seconds: int = 3_600,
    interval_seconds: int = 60,
    *,
    on_progress: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Repeatedly query loopback Ollama and report resource/latency drift.

    Requests use a fixed benign prompt; response text and exception messages are
    never retained or printed. The run stops after three consecutive failures.
    """
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, int)
        or not 1 <= duration_seconds <= 3_600
    ):
        raise ValueError("duration_seconds must be from 1 to 3600")
    if (
        isinstance(interval_seconds, bool)
        or not isinstance(interval_seconds, int)
        or not 1 <= interval_seconds <= 600
    ):
        raise ValueError("interval_seconds must be from 1 to 600")

    settings = get_settings()
    host = urlsplit(settings.local_ai_base_url).hostname
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Local AI soak only permits a loopback Ollama endpoint")

    engine = SHUAIEngine(settings)
    resident_before = engine.local_model_loaded()
    started = time.monotonic()
    deadline = started + duration_seconds
    next_request = started
    last_progress = started
    prompt = "Reply with exactly one word: READY"
    latencies: list[float] = []
    response_lengths: list[int] = []
    ollama_timings: list[dict[str, float | None]] = []
    cpu_percent_samples: list[float] = []
    memory_snapshots: list[dict[str, int]] = []
    disk_snapshots: list[dict[str, int]] = []
    failures: dict[str, int] = {}
    consecutive_failures = 0
    stop_reason = "duration_elapsed"

    memory = system_memory_snapshot()
    model_disk_size = ollama_model_disk_size(settings)
    disk = data_volume_snapshot(settings.data_dir)
    if disk is not None:
        disk_snapshots.append(disk)
    if memory is not None:
        memory_snapshots.append(memory)
        if memory["available_physical_bytes"] < _SOAK_MIN_AVAILABLE_MIB * 1024**2:
            stop_reason = "available_memory_below_safety_floor"

    while stop_reason == "duration_elapsed":
        now = time.monotonic()
        if now >= deadline:
            break
        if now < next_request:
            time.sleep(min(next_request - now, deadline - now))
            now = time.monotonic()
            if now >= deadline:
                break

        cpu_before = system_cpu_snapshot()
        request_started = time.perf_counter()
        try:
            answer, timing = ollama_chat(settings, prompt)
            response_lengths.append(len(answer))
            ollama_timings.append(timing)
            consecutive_failures = 0
        except Exception as error:
            error_name = type(error).__name__
            failures[error_name] = failures.get(error_name, 0) + 1
            consecutive_failures += 1
        latencies.append(time.perf_counter() - request_started)
        cpu_after = system_cpu_snapshot()
        cpu_percent = _cpu_percent(cpu_before, cpu_after)
        if cpu_percent is not None:
            cpu_percent_samples.append(cpu_percent)
        memory = system_memory_snapshot()
        if memory is not None:
            memory_snapshots.append(memory)
        disk = data_volume_snapshot(settings.data_dir)
        if disk is not None:
            disk_snapshots.append(disk)

        finished = time.monotonic()
        next_request = max(next_request + interval_seconds, finished)
        if (
            memory is not None
            and memory["available_physical_bytes"]
            < _SOAK_MIN_AVAILABLE_MIB * 1024**2
        ):
            stop_reason = "available_memory_below_safety_floor"
            break
        if consecutive_failures >= 3:
            stop_reason = "three_consecutive_request_failures"
            break
        if on_progress and finished - last_progress >= min(300, duration_seconds):
            on_progress(
                {
                    "elapsed_seconds": round(finished - started, 1),
                    "successful_requests": len(response_lengths),
                    "failed_requests": sum(failures.values()),
                    "resident": engine.local_model_loaded(),
                }
            )
            last_progress = finished

    elapsed = time.monotonic() - started
    report: dict[str, object] = {
        "model": settings.local_ai_model,
        "model_disk_size_bytes": model_disk_size,
        "model_disk_size_mib": (
            round(model_disk_size / (1024 * 1024), 1)
            if model_disk_size is not None
            else None
        ),
        "requested_duration_seconds": duration_seconds,
        "elapsed_seconds": round(elapsed, 1),
        "interval_seconds": interval_seconds,
        "minimum_available_memory_mib": _SOAK_MIN_AVAILABLE_MIB,
        "stop_reason": stop_reason,
        "target_duration_met": elapsed >= duration_seconds,
        "successful_requests": len(response_lengths),
        "failed_requests": sum(failures.values()),
        "failure_types": failures,
        "resident_before": resident_before,
        "resident_after": engine.local_model_loaded(),
        "request_latency_seconds": [round(value, 3) for value in latencies],
        "request_latency_median_seconds": (
            round(statistics.median(latencies), 3) if latencies else None
        ),
        "request_latency_p95_seconds": _percentile(latencies, 95),
        "request_latency_max_seconds": round(max(latencies), 3) if latencies else None,
        "response_characters": response_lengths,
        "prompt_content": "fixed benign prompt; response text is not emitted",
    }
    report.update(_memory_report(memory_snapshots))
    report.update(_disk_report(disk_snapshots))
    report.update(_cpu_report(cpu_percent_samples))
    report.update(_ollama_timing_report(ollama_timings))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        help="round trips to measure (1-100)",
    )
    parser.add_argument(
        "--soak-seconds",
        type=int,
        help="run a local-only Qwen stability soak (1-3600 seconds)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="seconds between soak requests (1-600; default 60)",
    )
    arguments = parser.parse_args()
    try:
        if arguments.soak_seconds is None:
            report = benchmark(arguments.samples)
        else:
            def report_progress(progress: dict[str, object]) -> None:
                print(json.dumps({"soak_progress": progress}), flush=True)

            report = soak(
                arguments.soak_seconds,
                arguments.interval_seconds,
                on_progress=report_progress,
            )
        print(json.dumps(report, indent=2), flush=True)
    except Exception as error:
        print(json.dumps({"error": type(error).__name__}))
        return 1
    if arguments.soak_seconds is not None and (
        report["failed_requests"] or not report["target_duration_met"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
