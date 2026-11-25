"""Emergency stop independent of AI model cooperation."""

from __future__ import annotations

import threading
import sys
from math import isfinite
from collections.abc import Callable


class EmergencyStop:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._callbacks: list[Callable[[], None]] = []

    @property
    def is_stopped(self) -> bool:
        return self._event.is_set()

    def add_callback(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def trigger(self) -> None:
        self._event.set()
        for callback in tuple(self._callbacks):
            try:
                callback()
            except Exception:
                # A broken stop callback must not prevent the remaining stops.
                continue

    def reset(self) -> None:
        """Re-arm only through an explicit UI/CLI user action."""
        self._event.clear()

    def check(self) -> None:
        if self.is_stopped:
            raise InterruptedError("SHU emergency stop is active")

    def wait_for_stop(self, timeout: float) -> bool:
        """Wait for the stop signal for a bounded interval; return if signaled."""
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not isfinite(timeout)
            or timeout < 0
        ):
            raise ValueError("Stop wait timeout must be a finite nonnegative number")
        return self._event.wait(timeout)


class WindowsEmergencyHotkey:
    """Register Ctrl+Alt+Pause for the lifetime of the SHU dashboard."""

    def __init__(self, stop: EmergencyStop, *, api_factory=None) -> None:
        self.stop_controller = stop
        self.api_factory = api_factory or _Win32HotkeyApi
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._api = None
        self._ready = threading.Event()
        self._startup_error: Exception | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._startup_error is None

    def start(self, *, timeout: float = 3.0) -> None:
        if sys.platform != "win32":
            raise OSError("The SHU global emergency hotkey is available on Windows only")
        if self.is_running:
            return
        self._ready.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._message_loop,
            name="shu-emergency-hotkey",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            self.stop()
            raise TimeoutError("The SHU emergency hotkey did not initialize")
        if self._startup_error is not None:
            self._thread.join(timeout=1.0)
            raise self._startup_error

    def stop(self, *, timeout: float = 3.0) -> None:
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        if self._api is not None and self._thread_id is not None:
            self._api.post_quit(self._thread_id)
        thread.join(timeout)
        if thread.is_alive():
            raise TimeoutError("The SHU emergency hotkey did not release cleanly")

    def _message_loop(self) -> None:
        registered = False
        try:
            api = self.api_factory()
            self._api = api
            self._thread_id = api.thread_id()
            api.create_message_queue()
            if not api.register():
                raise OSError(api.last_error(), "Could not register Ctrl+Alt+Pause")
            registered = True
            self._ready.set()
            while True:
                message = api.get_message()
                if message == "quit":
                    return
                if message == "hotkey":
                    self.stop_controller.trigger()
        except Exception as error:
            self._startup_error = error
            self._ready.set()
        finally:
            if registered:
                api.unregister()


class _Win32HotkeyApi:
    """Small ctypes wrapper kept behind the Windows-only listener thread."""

    hotkey_id = 0x5348
    wm_hotkey = 0x0312
    wm_quit = 0x0012
    mod_alt_control_norepeat = 0x0001 | 0x0002 | 0x4000
    vk_pause = 0x13

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.RegisterHotKey.restype = wintypes.BOOL
        self.user32.UnregisterHotKey.restype = wintypes.BOOL
        self.user32.GetMessageW.restype = wintypes.BOOL
        self.user32.PostThreadMessageW.restype = wintypes.BOOL
        self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    def thread_id(self) -> int:
        return int(self.kernel32.GetCurrentThreadId())

    def create_message_queue(self) -> None:
        message = self.wintypes.MSG()
        self.user32.PeekMessageW(self.ctypes.byref(message), None, 0, 0, 0)

    def register(self) -> bool:
        return bool(
            self.user32.RegisterHotKey(
                None,
                self.hotkey_id,
                self.mod_alt_control_norepeat,
                self.vk_pause,
            )
        )

    def get_message(self) -> str:
        message = self.wintypes.MSG()
        result = int(self.user32.GetMessageW(self.ctypes.byref(message), None, 0, 0))
        if result == -1:
            raise OSError(self.ctypes.get_last_error(), "Hotkey message loop failed")
        if result == 0:
            return "quit"
        if message.message == self.wm_hotkey and message.wParam == self.hotkey_id:
            return "hotkey"
        return "other"

    def post_quit(self, thread_id: int) -> None:
        if not self.user32.PostThreadMessageW(thread_id, self.wm_quit, 0, 0):
            raise OSError(self.ctypes.get_last_error(), "Could not stop the hotkey message loop")

    def unregister(self) -> None:
        self.user32.UnregisterHotKey(None, self.hotkey_id)

    @staticmethod
    def last_error() -> int:
        import ctypes

        return ctypes.get_last_error()
