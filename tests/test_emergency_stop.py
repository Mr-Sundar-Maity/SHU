import queue
import threading

import pytest

from app.security.emergency_stop import EmergencyStop, WindowsEmergencyHotkey


class FakeHotkeyApi:
    def __init__(self, *, register_ok=True):
        self.messages = queue.Queue()
        self.register_ok = register_ok
        self.unregistered = False
        self.queue_created = False

    def thread_id(self):
        return 123

    def create_message_queue(self):
        self.queue_created = True

    def register(self):
        return self.register_ok

    def last_error(self):
        return 1409

    def get_message(self):
        return self.messages.get(timeout=2)

    def post_quit(self, _thread_id):
        self.messages.put("quit")

    def unregister(self):
        self.unregistered = True


def test_global_hotkey_triggers_emergency_stop_and_releases_registration(monkeypatch):
    api = FakeHotkeyApi()
    stopped = threading.Event()
    controller = EmergencyStop()
    controller.add_callback(stopped.set)
    listener = WindowsEmergencyHotkey(controller, api_factory=lambda: api)
    monkeypatch.setattr("app.security.emergency_stop.sys.platform", "win32")

    listener.start()
    api.messages.put("hotkey")

    assert stopped.wait(1)
    listener.stop()
    assert api.queue_created
    assert api.unregistered


def test_global_hotkey_fails_closed_when_another_app_owns_the_combo(monkeypatch):
    api = FakeHotkeyApi(register_ok=False)
    listener = WindowsEmergencyHotkey(EmergencyStop(), api_factory=lambda: api)
    monkeypatch.setattr("app.security.emergency_stop.sys.platform", "win32")

    with pytest.raises(OSError, match="Could not register"):
        listener.start()

    assert not listener.is_running
    assert listener._thread is not None and not listener._thread.is_alive()


def test_global_hotkey_is_restricted_to_windows(monkeypatch):
    listener = WindowsEmergencyHotkey(EmergencyStop())
    monkeypatch.setattr("app.security.emergency_stop.sys.platform", "linux")

    with pytest.raises(OSError, match="Windows only"):
        listener.start()


def test_emergency_stop_wait_is_interruptible_and_timeout_is_bounded():
    controller = EmergencyStop()

    assert controller.wait_for_stop(0) is False
    controller.trigger()
    assert controller.wait_for_stop(1) is True


@pytest.mark.parametrize("timeout", [-1, float("inf"), float("nan"), True])
def test_emergency_stop_wait_rejects_invalid_timeouts(timeout):
    with pytest.raises(ValueError, match="finite nonnegative"):
        EmergencyStop().wait_for_stop(timeout)
