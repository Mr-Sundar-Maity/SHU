import pytest

from app.config import Settings
from scripts import benchmark_local_ai


def test_local_ai_benchmark_rejects_non_loopback_endpoints(monkeypatch):
    settings = Settings.from_env(
        {
            "LOCAL_AI_BASE_URL": "https://example.invalid",
            "LOCAL_AI_MODEL": "qwen2.5:1.5b",
        }
    )
    monkeypatch.setattr(benchmark_local_ai, "get_settings", lambda: settings)

    with pytest.raises(ValueError, match="loopback"):
        benchmark_local_ai.benchmark(1)


def test_local_ai_benchmark_reports_metadata_without_response_text(monkeypatch):
    settings = Settings.from_env(
        {
            "LOCAL_AI_BASE_URL": "http://127.0.0.1:11434",
            "LOCAL_AI_MODEL": "qwen2.5:1.5b",
        }
    )

    engines = []

    class FakeEngine:
        def __init__(self, _settings):
            self.calls = 0
            engines.append(self)

        def local_model_loaded(self):
            return self.calls > 0

    def fake_chat(_settings, prompt):
        assert prompt == "Reply with exactly one word: READY"
        engines[0].calls += 1
        return "private synthetic response", {
            "load_duration_seconds": 0.25,
            "server_total_duration_seconds": 0.45,
            "prompt_eval_duration_seconds": 0.05,
            "eval_duration_seconds": 0.15,
        }

    monkeypatch.setattr(benchmark_local_ai, "get_settings", lambda: settings)
    monkeypatch.setattr(benchmark_local_ai, "SHUAIEngine", FakeEngine)
    monkeypatch.setattr(
        benchmark_local_ai,
        "ollama_model_disk_size",
        lambda _settings: 1_500_000_000,
    )
    monkeypatch.setattr(benchmark_local_ai, "ollama_chat", fake_chat)
    disk_snapshots = iter(
        [
            {"total_bytes": 512 * 1024**3, "free_bytes": 80 * 1024**3},
            {"total_bytes": 512 * 1024**3, "free_bytes": 79 * 1024**3},
            {"total_bytes": 512 * 1024**3, "free_bytes": 78 * 1024**3},
        ]
    )
    monkeypatch.setattr(
        benchmark_local_ai,
        "data_volume_snapshot",
        lambda _path: next(disk_snapshots),
    )
    memory_snapshots = iter(
        [
            {
                "total_physical_bytes": 16 * 1024**3,
                "available_physical_bytes": 8 * 1024**3,
                "memory_load_percent": 50,
            },
            {
                "total_physical_bytes": 16 * 1024**3,
                "available_physical_bytes": 7 * 1024**3,
                "memory_load_percent": 56,
            },
            {
                "total_physical_bytes": 16 * 1024**3,
                "available_physical_bytes": 6 * 1024**3,
                "memory_load_percent": 62,
            },
        ]
    )
    monkeypatch.setattr(
        benchmark_local_ai,
        "system_memory_snapshot",
        lambda: next(memory_snapshots),
    )
    cpu_snapshots = iter(
        [
            {"idle": 100, "kernel": 1_000, "user": 1_000},
            {"idle": 110, "kernel": 1_060, "user": 1_030},
            {"idle": 210, "kernel": 2_060, "user": 2_030},
            {"idle": 230, "kernel": 2_130, "user": 2_060},
        ]
    )
    monkeypatch.setattr(
        benchmark_local_ai,
        "system_cpu_snapshot",
        lambda: next(cpu_snapshots),
    )

    report = benchmark_local_ai.benchmark(2)

    assert report["model"] == "qwen2.5:1.5b"
    assert report["model_disk_size_bytes"] == 1_500_000_000
    assert report["model_disk_size_mib"] == round(1_500_000_000 / (1024 * 1024), 1)
    assert report["samples"] == 2
    assert report["response_characters"] == [len("private synthetic response")] * 2
    assert "private synthetic response" not in repr(report)
    assert report["model_load_seconds_samples"] == [0.25, 0.25]
    assert report["model_load_seconds_median"] == 0.25
    assert report["server_total_seconds_median"] == 0.45
    assert report["data_volume_samples"] == 3
    assert report["data_volume_total_mib"] == 512 * 1024
    assert report["data_volume_free_mib_before"] == 80 * 1024
    assert report["data_volume_free_mib_min"] == 78 * 1024
    assert report["data_volume_free_mib_after"] == 78 * 1024
    assert report["system_memory_samples"] == 3
    assert report["system_total_physical_mb"] == 16 * 1024
    assert report["system_available_memory_mb_before"] == 8 * 1024
    assert report["system_available_memory_mb_min"] == 6 * 1024
    assert report["system_available_memory_mb_after"] == 6 * 1024
    assert report["system_memory_load_percent_peak"] == 62
    assert report["system_cpu_scope"] == "whole system during each request"
    assert report["system_cpu_samples"] == 2
    assert report["system_cpu_percent_samples"] == [88.9, 80.0]
    assert report["system_cpu_percent_median"] == 84.4
    assert report["system_cpu_percent_peak"] == 88.9
    assert report["min_seconds"] <= report["p95_seconds"] <= report["max_seconds"]


def test_ollama_disk_and_response_metadata_are_read_from_local_api(monkeypatch):
    settings = Settings.from_env(
        {
            "LOCAL_AI_BASE_URL": "http://127.0.0.1:11434",
            "LOCAL_AI_MODEL": "qwen2.5:1.5b",
        }
    )

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self.data

    monkeypatch.setattr(
        benchmark_local_ai.requests,
        "get",
        lambda url, **_kwargs: (
            FakeResponse(
                {
                    "models": [
                        {"name": "other:latest", "size": 10},
                        {"model": "QWEN2.5:1.5B", "size": 1_500_000_000},
                    ]
                }
            )
            if url.endswith("/api/tags")
            else pytest.fail("unexpected local GET endpoint")
        ),
    )
    monkeypatch.setattr(
        benchmark_local_ai.requests,
        "post",
        lambda url, **_kwargs: FakeResponse(
            {
                "message": {"role": "assistant", "content": "READY"},
                "load_duration": 250_000_000,
                "total_duration": 450_000_000,
                "prompt_eval_duration": 50_000_000,
                "eval_duration": 150_000_000,
            }
        )
        if url.endswith("/api/chat")
        else pytest.fail("unexpected local POST endpoint"),
    )

    assert benchmark_local_ai.ollama_model_disk_size(settings) == 1_500_000_000
    answer, timings = benchmark_local_ai.ollama_chat(settings, "READY")
    assert answer == "READY"
    assert timings == {
        "load_duration_seconds": 0.25,
        "server_total_duration_seconds": 0.45,
        "prompt_eval_duration_seconds": 0.05,
        "eval_duration_seconds": 0.15,
    }


def test_ollama_duration_and_data_volume_helpers_handle_missing_values(
    monkeypatch, tmp_path
):
    assert benchmark_local_ai._duration_seconds(None) is None
    assert benchmark_local_ai._duration_seconds(True) is None
    assert benchmark_local_ai._duration_seconds(-1) is None
    assert benchmark_local_ai._duration_seconds(10**1000) is None
    assert benchmark_local_ai._duration_seconds(1_000_000_000) == 1.0
    monkeypatch.setattr(
        benchmark_local_ai.shutil,
        "disk_usage",
        lambda _path: type("Usage", (), {"total": 100, "free": 40})(),
    )
    assert benchmark_local_ai.data_volume_snapshot(tmp_path / "missing") == {
        "total_bytes": 100,
        "free_bytes": 40,
    }


def test_ollama_model_disk_size_is_unavailable_for_unknown_or_invalid_tag(monkeypatch):
    settings = Settings.from_env(
        {
            "LOCAL_AI_BASE_URL": "http://127.0.0.1:11434",
            "LOCAL_AI_MODEL": "qwen2.5:1.5b",
        }
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "qwen2.5:1.5b", "size": "large"}]}

    monkeypatch.setattr(
        benchmark_local_ai.requests,
        "get",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    assert benchmark_local_ai.ollama_model_disk_size(settings) is None


def test_cpu_percent_rejects_unavailable_or_invalid_snapshots():
    assert benchmark_local_ai._cpu_percent(None, None) is None
    assert benchmark_local_ai._cpu_percent(
        {"idle": 20, "kernel": 10, "user": 10},
        {"idle": 21, "kernel": 10, "user": 10},
    ) is None
    assert benchmark_local_ai._cpu_percent(
        {"idle": 10, "kernel": 20, "user": 20},
        {"idle": 9, "kernel": 21, "user": 21},
    ) is None


def test_percentile_uses_inclusive_linear_interpolation():
    assert benchmark_local_ai._percentile([], 95) is None
    assert benchmark_local_ai._percentile([2.0], 95) == 2.0
    assert benchmark_local_ai._percentile([30.0, 0.0, 20.0, 10.0], 95) == 28.5
    with pytest.raises(ValueError, match="between 0 and 100"):
        benchmark_local_ai._percentile([1.0], 101)


def test_local_ai_benchmark_rejects_more_than_100_samples():
    with pytest.raises(ValueError, match="1 to 100"):
        benchmark_local_ai.benchmark(101)


def test_local_ai_soak_repeats_fixed_local_prompt_and_hides_response_text(monkeypatch):
    settings = Settings.from_env(
        {
            "LOCAL_AI_BASE_URL": "http://127.0.0.1:11434",
            "LOCAL_AI_MODEL": "qwen2.5:1.5b",
        }
    )

    class FakeClock:
        now = 0.0

        def monotonic(self):
            return self.now

        def perf_counter(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = FakeClock()

    engines = []

    class FakeEngine:
        def __init__(self, _settings):
            self.calls = 0
            engines.append(self)

        def local_model_loaded(self):
            return self.calls > 0

    def fake_chat(_settings, prompt):
        assert prompt == "Reply with exactly one word: READY"
        engines[0].calls += 1
        clock.now += 0.1
        return "private synthetic response", {
            "load_duration_seconds": 0.01,
            "server_total_duration_seconds": 0.1,
            "prompt_eval_duration_seconds": 0.02,
            "eval_duration_seconds": 0.05,
        }

    monkeypatch.setattr(benchmark_local_ai, "get_settings", lambda: settings)
    monkeypatch.setattr(benchmark_local_ai, "SHUAIEngine", FakeEngine)
    monkeypatch.setattr(benchmark_local_ai, "ollama_model_disk_size", lambda _settings: None)
    monkeypatch.setattr(benchmark_local_ai, "ollama_chat", fake_chat)
    monkeypatch.setattr(benchmark_local_ai, "data_volume_snapshot", lambda _path: None)
    monkeypatch.setattr(benchmark_local_ai.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(benchmark_local_ai.time, "perf_counter", clock.perf_counter)
    monkeypatch.setattr(benchmark_local_ai.time, "sleep", clock.sleep)
    monkeypatch.setattr(benchmark_local_ai, "system_memory_snapshot", lambda: None)
    monkeypatch.setattr(benchmark_local_ai, "system_cpu_snapshot", lambda: None)

    report = benchmark_local_ai.soak(5, 2)

    assert report["target_duration_met"] is True
    assert report["requested_duration_seconds"] == 5
    assert report["successful_requests"] == 3
    assert report["failed_requests"] == 0
    assert report["resident_before"] is False
    assert report["resident_after"] is True
    assert report["request_latency_median_seconds"] == 0.1
    assert report["request_latency_p95_seconds"] == 0.1
    assert report["model_load_seconds_samples"] == [0.01, 0.01, 0.01]
    assert report["server_total_seconds_median"] == 0.1
    assert "private synthetic response" not in repr(report)


def test_local_ai_soak_stops_after_three_consecutive_failures(monkeypatch):
    settings = Settings.from_env(
        {
            "LOCAL_AI_BASE_URL": "http://127.0.0.1:11434",
            "LOCAL_AI_MODEL": "qwen2.5:1.5b",
        }
    )

    class FakeClock:
        now = 0.0

        def monotonic(self):
            return self.now

        def perf_counter(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = FakeClock()

    class FailingEngine:
        def __init__(self, _settings):
            self.calls = 0

        def local_model_loaded(self):
            return False

    engine = FailingEngine(settings)

    def fail_chat(_settings, _prompt):
        engine.calls += 1
        clock.now += 0.1
        raise TimeoutError("synthetic timeout detail")

    monkeypatch.setattr(benchmark_local_ai, "get_settings", lambda: settings)
    monkeypatch.setattr(benchmark_local_ai, "SHUAIEngine", lambda _settings: engine)
    monkeypatch.setattr(benchmark_local_ai, "ollama_model_disk_size", lambda _settings: None)
    monkeypatch.setattr(benchmark_local_ai, "ollama_chat", fail_chat)
    monkeypatch.setattr(benchmark_local_ai, "data_volume_snapshot", lambda _path: None)
    monkeypatch.setattr(benchmark_local_ai.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(benchmark_local_ai.time, "perf_counter", clock.perf_counter)
    monkeypatch.setattr(benchmark_local_ai.time, "sleep", clock.sleep)
    monkeypatch.setattr(benchmark_local_ai, "system_memory_snapshot", lambda: None)
    monkeypatch.setattr(benchmark_local_ai, "system_cpu_snapshot", lambda: None)

    report = benchmark_local_ai.soak(60, 2)

    assert report["target_duration_met"] is False
    assert report["stop_reason"] == "three_consecutive_request_failures"
    assert report["successful_requests"] == 0
    assert report["failed_requests"] == 3
    assert report["failure_types"] == {"TimeoutError": 3}
    assert "synthetic timeout detail" not in repr(report)


def test_local_ai_soak_stops_below_memory_safety_floor(monkeypatch):
    settings = Settings.from_env(
        {
            "LOCAL_AI_BASE_URL": "http://127.0.0.1:11434",
            "LOCAL_AI_MODEL": "qwen2.5:1.5b",
        }
    )

    class FakeClock:
        now = 0.0

        def monotonic(self):
            return self.now

        def perf_counter(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = FakeClock()

    engines = []

    class FakeEngine:
        def __init__(self, _settings):
            self.calls = 0
            engines.append(self)

        def local_model_loaded(self):
            return self.calls > 0


    def fake_chat(_settings, _prompt):
        engines[0].calls += 1
        clock.now += 0.1
        return "READY", {
            "load_duration_seconds": 0.01,
            "server_total_duration_seconds": 0.1,
            "prompt_eval_duration_seconds": 0.02,
            "eval_duration_seconds": 0.05,
        }

    memory_snapshots = iter(
        [
            {
                "total_physical_bytes": 20 * 1024**3,
                "available_physical_bytes": 4 * 1024**3,
                "memory_load_percent": 80,
            },
            {
                "total_physical_bytes": 20 * 1024**3,
                "available_physical_bytes": 1 * 1024**3,
                "memory_load_percent": 95,
            },
        ]
    )
    monkeypatch.setattr(benchmark_local_ai, "get_settings", lambda: settings)
    monkeypatch.setattr(benchmark_local_ai, "SHUAIEngine", FakeEngine)
    monkeypatch.setattr(benchmark_local_ai, "ollama_model_disk_size", lambda _settings: None)
    monkeypatch.setattr(benchmark_local_ai, "ollama_chat", fake_chat)
    monkeypatch.setattr(benchmark_local_ai, "data_volume_snapshot", lambda _path: None)
    monkeypatch.setattr(benchmark_local_ai.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(benchmark_local_ai.time, "perf_counter", clock.perf_counter)
    monkeypatch.setattr(benchmark_local_ai.time, "sleep", clock.sleep)
    monkeypatch.setattr(
        benchmark_local_ai,
        "system_memory_snapshot",
        lambda: next(memory_snapshots),
    )
    monkeypatch.setattr(benchmark_local_ai, "system_cpu_snapshot", lambda: None)

    report = benchmark_local_ai.soak(60, 2)

    assert report["target_duration_met"] is False
    assert report["stop_reason"] == "available_memory_below_safety_floor"
    assert report["successful_requests"] == 1
    assert report["system_available_memory_mb_min"] == 1024


@pytest.mark.parametrize(
    ("duration", "interval", "message"),
    [
        (0, 1, "duration_seconds"),
        (3601, 1, "duration_seconds"),
        (10, 0, "interval_seconds"),
        (10, 601, "interval_seconds"),
    ],
)
def test_local_ai_soak_bounds_duration_and_interval(duration, interval, message):
    with pytest.raises(ValueError, match=message):
        benchmark_local_ai.soak(duration, interval)

