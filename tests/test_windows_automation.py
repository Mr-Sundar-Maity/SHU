from types import SimpleNamespace
import hashlib
import subprocess
import sys
from unittest.mock import Mock

import pytest

from app.automation.registered_tools import register_safe_desktop_tools
from app.automation.windows import WindowsAutomation
from app.security.policy import PolicyDenied, RiskLevel
from app.security.registry import ToolRegistry
from app.tasks.executor import TaskExecutor
from app.tasks.planner import InvalidPlan, TaskPlanner
from database.database import Database


class FakeControl:
    def __init__(
        self, name, value="", *, password=False, visible=True, enabled=True,
        editable=True, control_type="Edit", checked=False, selected=False,
        state_on_click=None,
    ):
        self.element_info = SimpleNamespace(
            name=name,
            control_type=control_type,
            automation_id="edit-1",
            enabled=enabled,
            visible=visible,
            element=SimpleNamespace(CurrentIsPassword=password),
        )
        self.value = value
        self._visible = visible
        self._enabled = enabled
        self._editable = editable
        self._checked = checked
        self._selected = selected
        self._state_on_click = state_on_click
        self.click_count = 0

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return self._enabled

    def is_editable(self):
        return self._editable

    def get_value(self):
        return self.value

    def set_edit_text(self, value):
        self.value = value

    def get_toggle_state(self):
        return int(self._checked)

    def is_selected(self):
        return self._selected

    def click_input(self):
        self.click_count += 1
        if self._state_on_click == "disabled":
            self._enabled = False
        elif self._state_on_click == "hidden":
            self._visible = False
        elif self.element_info.control_type == "CheckBox":
            self._checked = not self._checked
        elif self.element_info.control_type in {"RadioButton", "TabItem"}:
            self._selected = True


class FakeWindow:
    def __init__(self, title, controls):
        self.title = title
        self.controls = controls

    def window_text(self):
        return self.title

    def is_visible(self):
        return True

    def is_minimized(self):
        return False

    def descendants(self):
        return self.controls


class FakeDesktop:
    def __init__(self, windows):
        self._windows = windows

    def windows(self):
        return self._windows


def automation_for(monkeypatch, windows, tmp_path):
    monkeypatch.setattr("app.automation.windows.sys.platform", "win32")
    return WindowsAutomation(
        [tmp_path],
        desktop_factory=lambda: FakeDesktop(windows),
    )


def test_copy_allowed_file_requires_approval_and_verifies_reviewed_bytes(tmp_path):
    root = tmp_path / "exports"
    root.mkdir()
    source, target = root / "note.txt", root / "note copy.txt"
    data = b"Synthetic file content"
    source.write_bytes(data)
    automation = WindowsAutomation([root])
    database = Database(tmp_path / "test.db")
    database.initialize()
    registry = ToolRegistry(database)
    register_safe_desktop_tools(registry, automation)
    preview = registry.execute("preview_allowed_file", {"path": str(source)})
    assert preview.value == {
        "path": str(source), "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }
    arguments = {"source": str(source), "destination": str(target), "expected_sha256": preview.value["sha256"]}

    with pytest.raises(PolicyDenied):
        registry.execute("copy_allowed_file", arguments)
    assert not target.exists()

    def approve(tool, shown_arguments, risk):
        assert tool == "copy_allowed_file"
        assert shown_arguments == arguments
        assert risk == RiskLevel.MODIFICATION
        return True

    copied = registry.execute("copy_allowed_file", arguments, confirm=approve)
    assert copied.verified
    assert copied.value["size"] == len(data)
    assert source.read_bytes() == target.read_bytes() == data
    assert not source.samefile(target)
    assert not list(root.glob(".shu-copy-*.part"))


def test_copy_allowed_file_refuses_existing_target_and_stale_preview(tmp_path):
    source, target = tmp_path / "source.txt", tmp_path / "existing.txt"
    source.write_text("Reviewed bytes", encoding="utf-8")
    target.write_text("Existing bytes", encoding="utf-8")
    automation = WindowsAutomation([tmp_path])
    digest = automation.preview_allowed_file(source)["sha256"]

    with pytest.raises(FileExistsError):
        automation.copy_allowed_file(str(source), str(target), digest, approved=True)
    assert target.read_text(encoding="utf-8") == "Existing bytes"

    source.write_text("Changed bytes", encoding="utf-8")
    unused = tmp_path / "unused.txt"
    with pytest.raises(ValueError, match="source changed since preview"):
        automation.copy_allowed_file(str(source), str(unused), digest, approved=True)
    assert not unused.exists()


def test_file_tools_refuse_paths_outside_allowed_root(tmp_path):
    root = tmp_path / "exports"
    root.mkdir()
    source = root / "source.txt"
    source.write_text("Approved bytes", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("Other bytes", encoding="utf-8")
    automation = WindowsAutomation([root])

    with pytest.raises(PermissionError, match="allowed directories"):
        automation.preview_allowed_file(outside)
    digest = automation.preview_allowed_file(source)["sha256"]
    with pytest.raises(PermissionError, match="allowed directories"):
        automation.copy_allowed_file(str(source), str(outside), digest, approved=True)
    assert outside.read_text(encoding="utf-8") == "Other bytes"


def test_failed_staging_verification_never_publishes_copy(monkeypatch, tmp_path):
    source, target = tmp_path / "source.txt", tmp_path / "target.txt"
    source.write_text("Reviewed bytes", encoding="utf-8")
    automation = WindowsAutomation([tmp_path])
    digest = automation.preview_allowed_file(source)["sha256"]

    monkeypatch.setattr("app.automation.windows.hashlib.file_digest", lambda *_args: hashlib.sha256(b"wrong"))
    with pytest.raises(OSError, match="Staged copy did not match"):
        automation.copy_allowed_file(str(source), str(target), digest, approved=True)
    assert not target.exists()
    assert not list(tmp_path.glob(".shu-copy-*.part"))


def test_inspect_window_returns_bounded_metadata_without_control_values(monkeypatch, tmp_path):
    control = FakeControl("Search", value="private text")
    automation = automation_for(monkeypatch, [FakeWindow("Notepad", [control])], tmp_path)

    report = automation.inspect_window("Notepad")

    assert report["trust"] == "local_ui_metadata"
    assert report["controls"][0]["name"] == "Search"
    assert report["controls"][0]["is_password"] is False
    assert "private text" not in repr(report)


def test_uia_fill_only_sets_one_empty_non_password_edit_control(monkeypatch, tmp_path):
    control = FakeControl("Message")
    automation = automation_for(monkeypatch, [FakeWindow("Composer", [control])], tmp_path)

    result = automation.fill_empty_text_control("Composer", "Message", "Hello")

    assert control.value == "Hello"
    assert result["verified"] is True
    assert result["submitted"] is False
    assert result["sha256"]


@pytest.mark.parametrize(
    ("controls", "message"),
    [
        ([FakeControl("Message", value="existing")], "will not overwrite"),
        ([FakeControl("Password", password=True)], "Password and protected"),
        ([FakeControl("Message"), FakeControl("Message")], "match exactly one"),
        ([FakeControl("Message", editable=False)], "read-only"),
    ],
)
def test_uia_fill_rejects_overwrite_protected_ambiguous_and_read_only(
    monkeypatch, tmp_path, controls, message
):
    automation = automation_for(monkeypatch, [FakeWindow("Composer", controls)], tmp_path)
    with pytest.raises((PermissionError, ValueError), match=message):
        automation.fill_empty_text_control("Composer", controls[0].element_info.name, "text")


def test_mouse_click_requires_approval_and_targets_one_visible_named_control(monkeypatch, tmp_path):
    button = FakeControl("Save", control_type="Button", state_on_click="disabled")
    automation = automation_for(monkeypatch, [FakeWindow("Editor", [button])], tmp_path)

    with pytest.raises(PermissionError, match="explicit approval"):
        automation.click_visible_control("Editor", "Save", "disabled")
    assert button.click_count == 0

    result = automation.click_visible_control(
        "Editor", "Save", "disabled", approved=True
    )

    assert button.click_count == 1
    assert result == {
        "window_title": "Editor",
        "control_name": "Save",
        "control_type": "Button",
        "expected_state": "disabled",
        "input_dispatched": True,
        "postcondition_verified": True,
        "already_satisfied": False,
    }


@pytest.mark.parametrize(
    ("controls", "minimized", "message"),
    [
        ([FakeControl("Search", control_type="Edit")], False, "supported clickable"),
        ([FakeControl("Save", control_type="Button"), FakeControl("Save", control_type="Button")], False, "match exactly one"),
        ([FakeControl("Save", control_type="Button", visible=False)], False, "visible and enabled"),
        ([FakeControl("Save", control_type="Button", enabled=False)], False, "visible and enabled"),
        ([FakeControl("Save", control_type="Button")], True, "not be minimized"),
    ],
)
def test_mouse_click_rejects_ambiguous_hidden_or_noninteractive_controls(
    monkeypatch, tmp_path, controls, minimized, message
):
    window = FakeWindow("Editor", controls)
    window.is_minimized = lambda: minimized
    automation = automation_for(monkeypatch, [window], tmp_path)

    with pytest.raises((PermissionError, ValueError), match=message):
        automation.click_visible_control(
            "Editor", "Save", "disabled", approved=True
        )


def test_uia_fill_is_registered_as_approval_gated_and_verified(monkeypatch, tmp_path):
    control = FakeControl("Message")
    automation = automation_for(monkeypatch, [FakeWindow("Composer", [control])], tmp_path)
    database = Database(tmp_path / "shu.db")
    database.initialize()
    registry = ToolRegistry(database)
    register_safe_desktop_tools(registry, automation)
    tool = next(item for item in registry.list_tools() if item.name == "fill_empty_text_control")

    assert tool.risk is RiskLevel.MODIFICATION
    with pytest.raises(PolicyDenied):
        registry.execute(
            "fill_empty_text_control",
            {"window_title": "Composer", "control_name": "Message", "text": "Hello"},
        )
    result = registry.execute(
        "fill_empty_text_control",
        {"window_title": "Composer", "control_name": "Message", "text": "Hello"},
        confirm=lambda *_args: True,
    )
    assert result.verified
    assert result.value["submitted"] is False


def test_mouse_click_tool_is_explicitly_approval_gated_and_audited(monkeypatch, tmp_path):
    checkbox = FakeControl("Remember", control_type="CheckBox")
    automation = automation_for(monkeypatch, [FakeWindow("Editor", [checkbox])], tmp_path)
    database = Database(tmp_path / "mouse.db")
    database.initialize()
    registry = ToolRegistry(database)
    register_safe_desktop_tools(registry, automation)

    with pytest.raises(PermissionError):
        registry.execute(
            "click_visible_control",
            {
                "window_title": "Editor",
                "control_name": "Remember",
                "expected_state": "checked",
            },
        )
    assert checkbox.click_count == 0

    result = registry.execute(
        "click_visible_control",
        {
            "window_title": "Editor",
            "control_name": "Remember",
            "expected_state": "checked",
        },
        confirm=lambda *_args: True,
    )
    assert result.value["input_dispatched"] is True
    assert result.value["postcondition_verified"] is True
    assert checkbox.click_count == 1
    with database.connect() as connection:
        row = connection.execute(
            "SELECT risk,approval,result FROM audit_logs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    assert tuple(row) == ("L3", "approved", "success")


def test_mouse_click_does_not_repeat_or_report_success_when_postcondition_fails(
    monkeypatch, tmp_path
):
    button = FakeControl("Save", control_type="Button")
    automation = automation_for(monkeypatch, [FakeWindow("Editor", [button])], tmp_path)
    database = Database(tmp_path / "click-failure.db")
    database.initialize()
    registry = ToolRegistry(database)
    register_safe_desktop_tools(registry, automation)

    with pytest.raises(RuntimeError, match="postcondition verification failed"):
        registry.execute(
            "click_visible_control",
            {
                "window_title": "Editor",
                "control_name": "Save",
                "expected_state": "disabled",
            },
            confirm=lambda *_args: True,
        )

    assert button.click_count == 1
    with database.connect() as connection:
        row = connection.execute(
            "SELECT result FROM audit_logs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    assert row["result"] == "verification_failed"


def test_mouse_click_skips_already_satisfied_state(monkeypatch, tmp_path):
    checkbox = FakeControl("Remember", control_type="CheckBox", checked=True)
    automation = automation_for(monkeypatch, [FakeWindow("Editor", [checkbox])], tmp_path)

    result = automation.click_visible_control(
        "Editor", "Remember", "checked", approved=True
    )

    assert checkbox.click_count == 0
    assert result["input_dispatched"] is False
    assert result["already_satisfied"] is True
    assert result["postcondition_verified"] is True


def test_task_runner_does_not_retry_click_after_unverified_dispatch(monkeypatch, tmp_path):
    button = FakeControl("Save", control_type="Button")
    automation = automation_for(monkeypatch, [FakeWindow("Editor", [button])], tmp_path)
    database = Database(tmp_path / "click-task.db")
    database.initialize()
    registry = ToolRegistry(database)
    register_safe_desktop_tools(registry, automation)
    planner = TaskPlanner(database, registry)
    arguments = {
        "window_title": "Editor",
        "control_name": "Save",
        "expected_state": "disabled",
    }

    with pytest.raises(InvalidPlan, match="cannot be retried"):
        planner.create(
            "click Save",
            [{"tool": "click_visible_control", "arguments": arguments,
              "idempotent": True, "retries": 1}],
        )

    task_id = planner.create(
        "click Save",
        [{"tool": "click_visible_control", "arguments": arguments,
          "idempotent": True, "retries": 0}],
    )
    report = TaskExecutor(database, planner, registry).execute(
        task_id, confirm=lambda *_args: True
    )

    assert report["status"] == "partially_completed"
    assert report["steps"][0]["error"] == "RuntimeError"
    assert button.click_count == 1


def test_screen_ocr_uses_selected_region_and_keeps_capture_in_memory(monkeypatch, tmp_path):
    from PIL import ImageGrab

    class FakeImage:
        def save(self, stream, *, format):
            assert format == "PNG"
            stream.write(b"png-image")

    grab = Mock(return_value=FakeImage())
    monkeypatch.setattr(ImageGrab, "grab", grab)
    monkeypatch.setattr(WindowsAutomation, "_primary_screen_size", lambda _self: (1920, 1080))
    monkeypatch.setattr("app.automation.windows.sys.platform", "win32")
    monkeypatch.setattr("app.automation.windows.shutil.which", lambda _name: r"C:\Tools\tesseract.exe")
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["tesseract"], returncode=0, stdout="recognized text".encode(), stderr=b""
        )
    )
    monkeypatch.setattr("app.automation.windows.subprocess.run", run)
    automation = WindowsAutomation([tmp_path])

    result = automation.read_screen_text(10, 20, 300, 120)

    grab.assert_called_once_with(bbox=(10, 20, 310, 140))
    assert run.call_args.args[0] == [r"C:\Tools\tesseract.exe", "stdin", "stdout", "--psm", "6"]
    assert run.call_args.kwargs["input"] == b"png-image"
    assert run.call_args.kwargs["shell"] is False
    assert result["text"] == "recognized text"
    assert result["processing"] == "local_tesseract"
    assert result["screenshot_saved"] is False


def test_screen_ocr_tool_requires_explicit_approval(monkeypatch, tmp_path):
    automation = automation_for(monkeypatch, [], tmp_path)
    automation.read_screen_text = Mock(return_value={"text": "private region"})
    database = Database(tmp_path / "ocr.db")
    database.initialize()
    registry = ToolRegistry(database)
    register_safe_desktop_tools(registry, automation)
    arguments = {"left": 0, "top": 0, "width": 200, "height": 100}

    with pytest.raises(PermissionError, match="requires explicit user approval"):
        registry.execute("read_screen_text", arguments)
    automation.read_screen_text.assert_not_called()

    result = registry.execute(
        "read_screen_text", arguments, confirm=lambda *_args: True
    )
    assert result.value["text"] == "private region"
    assert result.verified
    automation.read_screen_text.assert_called_once_with(**arguments)
