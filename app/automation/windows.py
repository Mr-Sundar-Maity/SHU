"""Constrained Windows application launching and window inspection."""

from __future__ import annotations

import os
import hashlib
import ctypes
import io
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PureWindowsPath

from app.automation.file_move import move_reviewed_file
from app.automation.paths import PathPolicy


_ALLOWED_APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "explorer": "explorer.exe",
}
_CLICK_VERIFY_TIMEOUT_SECONDS = 2.0
_MAX_FILE_COPY_BYTES = 64 * 1024 * 1024


class WindowsAutomation:
    CLICK_EXPECTED_STATES = frozenset(
        {"checked", "unchecked", "selected", "unselected", "hidden", "disabled"}
    )

    def __init__(self, allowed_roots: list[str | Path], *, desktop_factory=None) -> None:
        self.paths = PathPolicy(allowed_roots)
        self.desktop_factory = desktop_factory

    def launch_application(self, app_id: str) -> dict[str, object]:
        if sys.platform != "win32":
            raise OSError("Desktop application launching is available on Windows only")
        executable_name = _ALLOWED_APPS.get(app_id.lower())
        if not executable_name:
            raise ValueError("Application is not in SHU's launch allowlist")
        executable = shutil.which(executable_name)
        if executable is None and app_id.lower() == "notepad":
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            candidate = Path(system_root) / "System32" / executable_name
            executable = str(candidate) if candidate.exists() else None
        if executable is None:
            raise FileNotFoundError(f"Allowed application is unavailable: {app_id}")
        print(f"SHU: Opening {app_id}...")
        process = subprocess.Popen([executable], shell=False, close_fds=True)
        return {"app_id": app_id.lower(), "process_id": process.pid}

    def list_windows(self) -> list[dict[str, str]]:
        windows = self._windows()
        return [
            {"title": window.window_text()[:300], "control_type": window.friendly_class_name()[:100]}
            for window in windows
            if window.window_text().strip()
        ]

    def inspect_window(self, title: str) -> dict[str, object]:
        """Return bounded UIA metadata for one exactly titled visible window."""
        window = self._exact_window(title)
        controls = []
        for control in window.descendants()[:200]:
            info = control.element_info
            try:
                is_password = self._is_password_control(info)
            except Exception:
                is_password = None
            controls.append(
                {
                    "name": str(info.name or "")[:300],
                    "control_type": str(info.control_type or "")[:80],
                    "automation_id": str(info.automation_id or "")[:120],
                    "enabled": bool(info.enabled),
                    "visible": bool(info.visible),
                    "is_password": is_password,
                }
            )
        return {"title": title, "controls": controls, "trust": "local_ui_metadata"}

    def fill_empty_text_control(
        self,
        window_title: str,
        control_name: str,
        text: str,
    ) -> dict[str, object]:
        """Fill one uniquely named, empty, non-password UIA Edit control.

        This prepares a visible field but never clicks Submit or presses Enter.
        Existing values and protected/password controls are always rejected.
        """
        if not isinstance(control_name, str) or not control_name.strip():
            raise ValueError("A non-empty UI Automation control name is required")
        if not isinstance(text, str) or not text or len(text) > 2_000:
            raise ValueError("Text must contain 1-2000 characters")

        window = self._exact_window(window_title)
        matches = [
            control
            for control in window.descendants()
            if control.element_info.control_type == "Edit"
            and control.element_info.name == control_name
        ]
        if len(matches) != 1:
            raise ValueError("The named text control must match exactly one Edit control")
        control = matches[0]
        if not control.is_visible() or not control.is_enabled():
            raise PermissionError("The text control must be visible and enabled")
        if hasattr(control, "is_editable") and not control.is_editable():
            raise PermissionError("The text control is read-only")
        try:
            is_password = self._is_password_control(control.element_info)
        except Exception as error:
            raise PermissionError("SHU cannot verify that the text control is not protected") from error
        if is_password:
            raise PermissionError("Password and protected controls are not supported")
        try:
            current_value = control.get_value()
        except Exception as error:
            raise PermissionError("SHU cannot safely verify the current field value") from error
        if current_value:
            raise PermissionError("SHU only fills an empty text control; it will not overwrite")

        control.set_edit_text(text)
        if control.get_value() != text:
            raise RuntimeError("UI Automation could not verify the entered text")
        return {
            "window_title": window_title,
            "control_name": control_name,
            "characters": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "verified": True,
            "submitted": False,
        }

    def click_visible_control(
        self,
        window_title: str,
        control_name: str,
        expected_state: str,
        *,
        approved: bool = False,
    ) -> dict[str, object]:
        """Click one visible control after approval and verify its requested UI state."""
        if approved is not True:
            raise PermissionError("Clicking a desktop control requires explicit approval")
        if not isinstance(control_name, str) or not control_name.strip() or len(control_name) > 200:
            raise ValueError("Control name must contain 1-200 characters")
        if expected_state not in self.CLICK_EXPECTED_STATES:
            raise ValueError("A supported expected UI state is required")

        window = self._exact_window(window_title)
        is_minimized = getattr(window, "is_minimized", None)
        if not callable(is_minimized):
            raise PermissionError("SHU cannot verify that the target window is not minimized")
        if is_minimized():
            raise PermissionError("The target application window must not be minimized")

        clickable_types = {
            "button", "checkbox", "hyperlink", "menuitem", "radiobutton", "tabitem",
        }
        matches = [
            control
            for control in window.descendants()
            if control.element_info.name == control_name
            and str(control.element_info.control_type or "").casefold() in clickable_types
        ]
        if len(matches) != 1:
            raise ValueError(
                "The control name must match exactly one supported clickable control"
            )
        control = matches[0]
        if not control.is_visible() or not control.is_enabled():
            raise PermissionError("The target control must be visible and enabled")
        control_type = str(control.element_info.control_type or "")
        if expected_state in {"checked", "unchecked"} and control_type.casefold() != "checkbox":
            raise ValueError("Checked-state verification requires a CheckBox control")
        if expected_state in {"selected", "unselected"} and control_type.casefold() not in {
            "radiobutton", "tabitem",
        }:
            raise ValueError("Selection verification requires a RadioButton or TabItem control")
        if self._click_state_matches(control, expected_state):
            return {
                "window_title": window_title,
                "control_name": control_name,
                "control_type": control_type,
                "expected_state": expected_state,
                "input_dispatched": False,
                "postcondition_verified": True,
                "already_satisfied": True,
            }
        click_input = getattr(control, "click_input", None)
        if not callable(click_input):
            raise PermissionError("SHU cannot send a physical click to this control")
        click_input()
        deadline = time.monotonic() + _CLICK_VERIFY_TIMEOUT_SECONDS
        verified = False
        while True:
            if self._click_postcondition_matches(
                window_title, control_name, control_type, expected_state
            ):
                verified = True
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        return {
            "window_title": window_title,
            "control_name": control_name,
            "control_type": control_type,
            "expected_state": expected_state,
            "input_dispatched": True,
            "postcondition_verified": verified,
            "already_satisfied": False,
        }

    @staticmethod
    def _click_state_matches(control, expected_state: str) -> bool:
        if expected_state == "hidden":
            return not control.is_visible()
        if expected_state == "disabled":
            return not control.is_enabled()
        if expected_state in {"checked", "unchecked"}:
            state_getter = getattr(control, "get_toggle_state", None)
            if not callable(state_getter):
                raise PermissionError("SHU cannot read the CheckBox toggle state")
            try:
                is_checked = int(state_getter()) == 1
            except Exception as error:
                raise PermissionError("SHU cannot verify the CheckBox toggle state") from error
            return is_checked if expected_state == "checked" else not is_checked
        selected_getter = getattr(control, "is_selected", None)
        if not callable(selected_getter):
            raise PermissionError("SHU cannot read the selection state")
        try:
            is_selected = bool(selected_getter())
        except Exception as error:
            raise PermissionError("SHU cannot verify the selection state") from error
        return is_selected if expected_state == "selected" else not is_selected

    def _click_postcondition_matches(
        self,
        window_title: str,
        control_name: str,
        control_type: str,
        expected_state: str,
    ) -> bool:
        try:
            windows = [
                window for window in self._windows()
                if window.window_text() == window_title
            ]
            if not windows:
                return expected_state == "hidden"
            if len(windows) != 1:
                return False
            controls = [
                candidate for candidate in windows[0].descendants()
                if candidate.element_info.name == control_name
                and str(candidate.element_info.control_type or "") == control_type
            ]
            if expected_state == "hidden":
                return not any(candidate.is_visible() for candidate in controls)
            if expected_state == "disabled":
                return bool(controls) and all(
                    not candidate.is_enabled() for candidate in controls
                )
            if len(controls) != 1:
                return False
            return self._click_state_matches(controls[0], expected_state)
        except Exception:
            return False

    def read_screen_text(
        self,
        left: int,
        top: int,
        width: int,
        height: int,
    ) -> dict[str, object]:
        """Capture a user-selected screen region in memory and OCR it locally."""
        if sys.platform != "win32":
            raise OSError("Screen capture is available on Windows only")
        values = (left, top, width, height)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("Screen region coordinates must be integers")
        if left < 0 or top < 0 or width < 1 or height < 1 or width * height > 8_294_400:
            raise ValueError("Screen region is invalid or exceeds the 4K pixel limit")
        try:
            from PIL import ImageGrab
        except ImportError as error:
            raise RuntimeError("Install Pillow to capture a screen region") from error

        screen_width, screen_height = self._primary_screen_size()
        if left + width > screen_width or top + height > screen_height:
            raise ValueError("Screen region extends beyond the current display")
        tesseract = shutil.which("tesseract")
        if tesseract is None:
            raise FileNotFoundError("Tesseract OCR is not installed or is not on PATH")
        screenshot = ImageGrab.grab(bbox=(left, top, left + width, top + height))
        payload = io.BytesIO()
        screenshot.save(payload, format="PNG")
        try:
            completed = subprocess.run(
                [tesseract, "stdin", "stdout", "--psm", "6"],
                input=payload.getvalue(),
                capture_output=True,
                timeout=20,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("Local screen OCR exceeded its 20 second limit") from error
        if completed.returncode != 0:
            raise RuntimeError("Local Tesseract OCR could not process the selected screen region")
        text = completed.stdout.decode("utf-8", errors="replace")[:12_000].strip()
        return {
            "region": {"left": left, "top": top, "width": width, "height": height},
            "text": text,
            "trust": "untrusted_screen_content",
            "processing": "local_tesseract",
            "screenshot_saved": False,
        }

    @staticmethod
    def _primary_screen_size() -> tuple[int, int]:
        """Return the primary Windows display dimensions in physical pixels."""
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    def list_allowed_files(self, directory: str | Path) -> list[dict[str, object]]:
        target = self.paths.resolve(directory, must_exist=True)
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        results = []
        for entry in sorted(target.iterdir(), key=lambda item: item.name.casefold()):
            # Do not follow links outside the allowlisted tree.
            resolved = self.paths.resolve(entry)
            results.append(
                {"name": entry.name, "is_dir": resolved.is_dir(), "size": resolved.stat().st_size if resolved.is_file() else None}
            )
        return results

    def preview_allowed_file(self, path: str | Path) -> dict[str, object]:
        """Return file review metadata without displaying the file's contents."""
        source = self._approved_file_path(path, must_exist=True)
        data = self._read_copy_source(source)
        return {"path": str(source), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def validate_copy_arguments(
        self, source: str, destination: str, expected_sha256: str,
    ) -> dict[str, str]:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
            raise ValueError("Use the 64-character SHA-256 from the file preview")
        source_path = self._approved_file_path(source, must_exist=True)
        target = self._approved_file_path(destination, must_exist=False)
        if target.exists():
            raise FileExistsError("The destination already exists")
        return {
            "source": str(source_path),
            "destination": str(target),
            "expected_sha256": expected_sha256.lower(),
        }

    def copy_allowed_file(
        self, source: str, destination: str, expected_sha256: str, *, approved: bool = False,
    ) -> dict[str, object]:
        """Publish a verified copy of the reviewed bytes at an unused name."""
        if not approved:
            raise PermissionError("Copying a file requires explicit approval")
        arguments = self.validate_copy_arguments(source, destination, expected_sha256)
        target = Path(arguments["destination"])
        data = self._read_copy_source(Path(arguments["source"]))
        digest = hashlib.sha256(data).hexdigest()
        if digest != arguments["expected_sha256"]:
            raise ValueError("The source changed since preview. Review it again before copying.")

        staged = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".shu-copy-", suffix=".part", delete=False,
            ) as stream:
                staged = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            with staged.open("rb") as stream:
                verified_digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if staged.stat().st_size != len(data) or verified_digest != digest:
                raise IOError("Staged copy did not match the reviewed file")
            # Publish the verified bytes as one entry. Linking cannot overwrite.
            os.link(staged, target)
            if not target.samefile(staged):
                raise IOError("Published copy did not match the verified staging file")
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
        return {**arguments, "size": len(data), "sha256": digest}

    def validate_move_arguments(
        self, source: str, destination: str, expected_sha256: str,
    ) -> dict[str, str]:
        arguments = self.validate_copy_arguments(source, destination, expected_sha256)
        self._common_move_root(Path(arguments["source"]), Path(arguments["destination"]))
        return arguments

    def move_allowed_file(
        self, source: str, destination: str, expected_sha256: str, *, approved: bool = False,
    ) -> dict[str, object]:
        """Rename a reviewed regular file and keep the former path available as an inverse."""
        if not approved:
            raise PermissionError("Moving a file requires explicit approval")
        arguments = self.validate_copy_arguments(source, destination, expected_sha256)
        source_path, target = Path(arguments["source"]), Path(arguments["destination"])
        root = self._common_move_root(source_path, target)
        digest = arguments["expected_sha256"]
        size = move_reviewed_file(source_path, target, root, digest, max_bytes=_MAX_FILE_COPY_BYTES)
        return {**arguments, "size": size, "sha256": digest, "source_absent": True}

    def _common_move_root(self, source: Path, destination: Path) -> Path:
        for root in self.paths.allowed_roots:
            if source.is_relative_to(root) and destination.is_relative_to(root):
                return root
        raise PermissionError("Move files within the same approved directory tree")

    def _approved_file_path(self, value: str | Path, *, must_exist: bool) -> Path:
        path = Path(value).expanduser().absolute()
        root = next((root for root in self.paths.allowed_roots if path.is_relative_to(root)), None)
        if root is None or path == root or ".." in path.parts:
            raise PermissionError("Use a file path inside SHU's allowed directories")
        entry = root
        for component in path.relative_to(root).parts:
            self.paths.validate_filename(component)
            if PureWindowsPath(component).is_reserved() or component.endswith((".", " ")):
                raise ValueError("Use a regular filename without reserved Windows names")
            entry /= component
            try:
                metadata = entry.lstat()
            except FileNotFoundError:
                if must_exist or entry != path:
                    raise
            else:
                if stat.S_ISLNK(metadata.st_mode) or (
                    getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise PermissionError("File tools do not follow links or junctions")
        return self.paths.resolve(path, must_exist=must_exist)

    @staticmethod
    def _read_copy_source(path: Path) -> bytes:
        if not path.is_file():
            raise ValueError("Select a regular file")
        with path.open("rb") as stream:
            data = stream.read(_MAX_FILE_COPY_BYTES + 1)
        if len(data) > _MAX_FILE_COPY_BYTES:
            raise ValueError("File preview and copying are limited to 64 MiB")
        return data

    def _windows(self):
        if sys.platform != "win32":
            raise OSError("Windows UI Automation is available on Windows only")
        if self.desktop_factory is not None:
            return self.desktop_factory().windows()
        from pywinauto import Desktop

        return Desktop(backend="uia").windows()

    def _exact_window(self, title: str):
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise ValueError("Window title must contain 1-300 characters")
        matches = [window for window in self._windows() if window.window_text() == title]
        if len(matches) != 1:
            raise ValueError("Window title must match exactly one open window")
        window = matches[0]
        if hasattr(window, "is_visible") and not window.is_visible():
            raise PermissionError("The target application window must be visible")
        return window

    @staticmethod
    def _is_password_control(element_info) -> bool:
        """Read UIA IsPasswordProperty; fail closed if the provider omits it."""
        element = element_info.element
        try:
            return bool(element.CurrentIsPassword)
        except AttributeError:
            return bool(element.GetCurrentPropertyValue(30019))
