from types import SimpleNamespace

import pytest

from app import system_metrics as metrics


def test_metrics_use_measured_cpu_deltas_and_throttle_reads(monkeypatch, tmp_path):
    times = [0.0]
    samples = iter(
        [
            {"idle": 100, "kernel": 200, "user": 100},
            {"idle": 120, "kernel": 250, "user": 150},
        ]
    )
    calls = []

    def cpu():
        calls.append("cpu")
        return next(samples)

    monkeypatch.setattr(metrics, "system_cpu_snapshot", cpu)
    monkeypatch.setattr(
        metrics,
        "system_memory_snapshot",
        lambda: {
            "total_physical_bytes": 10 * 1024**3,
            "available_physical_bytes": 4 * 1024**3,
            "memory_load_percent": 60,
        },
    )
    monkeypatch.setattr(
        metrics,
        "system_disk_snapshot",
        lambda path: {"total_bytes": 1000, "free_bytes": 600},
    )
    sampler = metrics.SystemMetrics(tmp_path, clock=lambda: times[0])
    initial = sampler.read()
    assert initial["cpuPercent"] is None
    assert initial["memoryUsedBytes"] == 6 * 1024**3
    assert initial["memoryPercent"] == 60
    assert initial["diskFreeBytes"] == 600
    initial["diskFreeBytes"] = 0
    times[0] = 1.9
    assert sampler.read()["diskFreeBytes"] == 600
    assert calls == ["cpu"]
    times[0] = 2.0
    assert sampler.read()["cpuPercent"] == 80.0
    assert calls == ["cpu", "cpu"]


def test_failed_samples_remove_stale_readings_and_reprime_cpu(monkeypatch, tmp_path):
    times = [0.0]
    samples = iter(
        [
            {"idle": 10, "kernel": 20, "user": 10},
            {"idle": 20, "kernel": 30, "user": 10},
            None,
            {"idle": 30, "kernel": 40, "user": 10},
            {"idle": 35, "kernel": 50, "user": 20},
        ]
    )
    monkeypatch.setattr(metrics, "system_cpu_snapshot", lambda: next(samples))
    monkeypatch.setattr(metrics, "system_memory_snapshot", lambda: None)
    monkeypatch.setattr(metrics, "system_disk_snapshot", lambda path: None)
    sampler = metrics.SystemMetrics(tmp_path, clock=lambda: times[0])
    values = []
    for time in range(0, 10, 2):
        times[0] = float(time)
        values.append(sampler.read())
    assert [s["cpuPercent"] for s in values] == [None, 0.0, None, None, 75.0]
    assert values[2]["sampledAt"] is None
    assert values[2]["memoryPercent"] is None
    assert values[2]["diskFreeBytes"] is None


@pytest.mark.parametrize("cpu_count", [None, 128])
def test_multiple_or_unknown_cpu_groups_are_not_reported_as_whole_system(monkeypatch, cpu_count):
    monkeypatch.setattr(metrics.sys, "platform", "win32")
    monkeypatch.setattr(metrics.os, "cpu_count", lambda: cpu_count)
    monkeypatch.setattr(
        metrics.ctypes,
        "WinDLL",
        lambda *a, **k: pytest.fail("No whole-system reading available"),
        raising=False,
    )
    assert metrics.system_cpu_snapshot() is None


@pytest.mark.parametrize("drive_type", [0, 1, 2, 4, 5, 6])
def test_non_fixed_drives_are_not_polled(monkeypatch, tmp_path, drive_type):
    monkeypatch.setattr(metrics.sys, "platform", "win32")
    monkeypatch.setattr(
        metrics.ctypes,
        "WinDLL",
        lambda *a, **k: SimpleNamespace(GetDriveTypeW=lambda root: drive_type),
        raising=False,
    )
    monkeypatch.setattr(
        metrics.shutil,
        "disk_usage",
        lambda path: pytest.fail("Do not query this drive"),
    )
    assert metrics.system_disk_snapshot(tmp_path) is None


def test_fixed_drive_reads_actual_disk_usage(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics.sys, "platform", "win32")
    monkeypatch.setattr(
        metrics.ctypes,
        "WinDLL",
        lambda *a, **k: SimpleNamespace(GetDriveTypeW=lambda root: 3),
        raising=False,
    )
    seen = []

    def usage(path):
        seen.append(path)
        return SimpleNamespace(total=2000, free=400)

    monkeypatch.setattr(metrics.shutil, "disk_usage", usage)
    assert metrics.system_disk_snapshot(tmp_path) == {
        "total_bytes": 2000,
        "free_bytes": 400,
    }
    assert seen == [tmp_path]


def test_unavailable_disk_is_not_presented_as_zero_free_space(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics.sys, "platform", "win32")
    monkeypatch.setattr(
        metrics.ctypes,
        "WinDLL",
        lambda *a, **k: SimpleNamespace(GetDriveTypeW=lambda root: 3),
        raising=False,
    )

    def unavailable(path):
        raise OSError("Synthetic device unavailable")

    monkeypatch.setattr(metrics.shutil, "disk_usage", unavailable)
    assert metrics.system_disk_snapshot(tmp_path) is None
