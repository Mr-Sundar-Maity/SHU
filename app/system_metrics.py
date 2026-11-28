"""Local Windows resource measurements shared by benchmarks and the dashboard."""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def system_memory_snapshot() -> dict[str, int] | None:
    """Capture Windows-wide physical-memory values without adding a dependency."""
    if sys.platform != "win32":
        return None

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatusEx)]
        kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return {
            "total_physical_bytes": int(status.ullTotalPhys),
            "available_physical_bytes": int(status.ullAvailPhys),
            "memory_load_percent": int(status.dwMemoryLoad),
        }
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def system_cpu_snapshot() -> dict[str, int] | None:
    """Capture cumulative Windows CPU times without adding a dependency."""
    cpu_count = os.cpu_count()
    if sys.platform != "win32" or cpu_count is None or cpu_count > 64:
        # GetSystemTimes covers only one processor group on larger machines.
        return None

    class FileTime(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", ctypes.c_uint32),
            ("dwHighDateTime", ctypes.c_uint32),
        ]

        def as_int(self) -> int:
            return (int(self.dwHighDateTime) << 32) | int(self.dwLowDateTime)

    try:
        idle = FileTime()
        kernel = FileTime()
        user = FileTime()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetSystemTimes.argtypes = [
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
        ]
        kernel32.GetSystemTimes.restype = ctypes.c_int
        if not kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None
        return {
            "idle": idle.as_int(),
            "kernel": kernel.as_int(),
            "user": user.as_int(),
        }
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def cpu_percent(
    before: dict[str, int] | None, after: dict[str, int] | None
) -> float | None:
    """Return whole-system non-idle CPU percentage between two snapshots."""
    if before is None or after is None:
        return None
    idle_delta = after["idle"] - before["idle"]
    kernel_delta = after["kernel"] - before["kernel"]
    user_delta = after["user"] - before["user"]
    total_delta = kernel_delta + user_delta
    if idle_delta < 0 or kernel_delta < 0 or user_delta < 0 or total_delta <= 0:
        return None
    busy_delta = total_delta - idle_delta
    if busy_delta < 0 or busy_delta > total_delta:
        return None
    return busy_delta * 100.0 / total_delta


def system_disk_snapshot(data_dir: Path) -> dict[str, int] | None:
    """Read free space for SHU's local fixed drive; skip network/removable drives."""
    if sys.platform != "win32":
        return None
    path = Path(data_dir)
    if not path.is_absolute() or str(path).startswith("\\\\"):
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetDriveTypeW.restype = ctypes.c_uint
        if kernel32.GetDriveTypeW(path.anchor) != 3:  # DRIVE_FIXED
            return None
        usage = shutil.disk_usage(path)
        return {"total_bytes": int(usage.total), "free_bytes": int(usage.free)}
    except (AttributeError, OSError, TypeError, ValueError):
        return None


class SystemMetrics:
    """Cache local readings; CPU is a measured delta, never an estimated load."""

    def __init__(
        self,
        data_dir: Path,
        *,
        interval_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if interval_seconds <= 0:
            raise ValueError("Sampling interval must be positive")
        self.data_dir = data_dir
        self.interval_seconds = interval_seconds
        self.clock = clock
        self._last_at: float | None = None
        self._previous_cpu: dict[str, int] | None = None
        self._snapshot: dict[str, object] = {}

    def read(self) -> dict[str, object]:
        now = self.clock()
        if self._last_at is not None and now - self._last_at < self.interval_seconds:
            return dict(self._snapshot)
        cpu = system_cpu_snapshot()
        cpu_load = cpu_percent(self._previous_cpu, cpu)
        memory = system_memory_snapshot()
        disk = system_disk_snapshot(self.data_dir)
        self._previous_cpu = cpu
        self._last_at = now
        self._snapshot = {
            "cpuPercent": round(cpu_load, 1) if cpu_load is not None else None,
            "memoryPercent": memory["memory_load_percent"] if memory else None,
            "memoryUsedBytes": (
                memory["total_physical_bytes"] - memory["available_physical_bytes"]
                if memory
                else None
            ),
            "memoryTotalBytes": memory["total_physical_bytes"] if memory else None,
            "diskFreeBytes": disk["free_bytes"] if disk else None,
            "sampledAt": (
                datetime.now(timezone.utc).isoformat()
                if cpu or memory or disk
                else None
            ),
        }
        return dict(self._snapshot)
