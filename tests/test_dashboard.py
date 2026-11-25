import json
import os
import gc
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDateTime, QEvent, QTimeZone, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import Settings
from app.applications.communications import CommunicationService
from app.interface.dashboard import SHUDashboard
from app.interface.dashboard import (
    _ChatWorker,
    _CommunicationSendWorker,
    _ProviderDraftWorker,
    _ReminderSpeechWorker,
    _TaskWorker,
)


@pytest.fixture(scope="session", autouse=True)
def keep_qapplication_alive():
    """Keep the main-thread Qt application alive through later worker-thread tests."""
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module", autouse=True)
def dispose_dashboard_objects(keep_qapplication_alive):
    yield
    # Dispose of Qt wrappers on the GUI thread before other tests start workers.
    keep_qapplication_alive.processEvents()
    keep_qapplication_alive.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def test_chat_worker_reports_provider_model_and_response(monkeypatch, tmp_path):
    from app.interface import dashboard

    settings = Settings.from_env({"SHU_DATA_DIR": str(tmp_path)})

    class FakeEngine:
        def __init__(self, passed_settings):
            assert passed_settings is settings

        def local_model_loaded(self):
            return False

        def ask(self, question, **kwargs):
            assert question == "Hello SHU"
            assert kwargs["context"] == []
            from app.config import response_style_instruction

            assert response_style_instruction("friendly") in kwargs["system_instruction"]
            kwargs["on_status"]("Generating with local model qwen2.5:1.5b")
            return "Hello!"

    monkeypatch.setattr(dashboard, "SHUAIEngine", FakeEngine)
    worker = _ChatWorker(settings, "Hello SHU", [])
    progress = []
    finished = []
    worker.progress.connect(progress.append)
    worker.finished.connect(lambda response, error: finished.append((response, error)))
    worker.run()

    assert progress == [
        f"Checking local model {settings.local_ai_model}",
        f"Loading local model {settings.local_ai_model}; first request may also download it",
        "Generating with local model qwen2.5:1.5b",
    ]
    assert finished == [("Hello!", "")]


def test_dashboard_marks_retrieved_memory_sensitive(tmp_path, monkeypatch):
    from app.interface import dashboard

    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_AI_PROVIDER": "google",
            "SHU_MICROPHONE_DEVICE": "",
        }
    )
    window = SHUDashboard(settings)
    memory_message = {
        "role": "user",
        "content": "APPROVED MEMORY DATA: prefers the blue theme",
    }
    calls = []

    class FakeRetriever:
        def context_messages(self, _question):
            return [memory_message]

    class FakeEngine:
        def __init__(self, passed_settings):
            assert passed_settings.ai_provider == "google"

        def ask(self, question, **kwargs):
            calls.append((question, kwargs))
            return "Response"

    monkeypatch.setattr(dashboard, "MemoryRetriever", lambda _manager: FakeRetriever())
    monkeypatch.setattr(dashboard, "SHUAIEngine", FakeEngine)
    window._run_worker = lambda worker, _callback: worker.run()
    window.input.setText("What preference did I save?")
    try:
        window._send_text()

        question, kwargs = calls[0]
        assert question == "What preference did I save?"
        assert kwargs["sensitive"] is True
        assert memory_message in kwargs["context"]
    finally:
        window.close()
    assert app is not None


def test_dashboard_reset_clears_chat_context_but_preserves_approved_memory(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {"SHU_DATA_DIR": str(tmp_path), "SHU_MICROPHONE_DEVICE": ""}
    )
    window = SHUDashboard(settings)
    saved = window.memories.add_memory(
        "prefers a short answer", approved=True
    )
    window.history.add("user", "temporary conversation detail")
    window.history.add("assistant", "temporary response")
    window.transcript.setPlainText(
        "You: temporary conversation detail\nSHU: temporary response"
    )
    window._last_voice_request = "temporary voice request"
    window._update_voice_plan_button()

    try:
        assert window.plan_voice_button.isEnabled()
        assert window.reset_conversation_button.accessibleName() == (
            "Reset conversation context"
        )
        window.reset_conversation_button.click()

        assert window.history.recent() == []
        assert window.transcript.toPlainText() == ""
        assert window._last_voice_request is None
        assert not window.plan_voice_button.isEnabled()
        assert window.memories.get_memory(saved.memory_id).content == (
            "prefers a short answer"
        )
        assert "approved saved memories are unchanged" in window.status.text()
    finally:
        window.close()
    assert app is not None


def test_dashboard_reset_control_is_disabled_during_chat_and_voice(
    tmp_path, monkeypatch
):
    from app.interface import dashboard

    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {"SHU_DATA_DIR": str(tmp_path), "SHU_MICROPHONE_DEVICE": ""}
    )
    window = SHUDashboard(settings)
    window._run_worker = lambda _worker, _callback: None

    class FakeAssistant:
        def __init__(self, *, settings, on_turn):
            self.settings = settings
            self.on_turn = on_turn

        def request_stop(self):
            pass

    try:
        window.input.setText("hello")
        window._send_text()
        assert not window.reset_conversation_button.isEnabled()
        window._chat_finished("reply", "")
        assert window.reset_conversation_button.isEnabled()

        monkeypatch.setattr(dashboard, "SHUVoiceAssistant", FakeAssistant)
        window._start_voice()
        assert not window.reset_conversation_button.isEnabled()
        window._voice_finished("")
        assert window.reset_conversation_button.isEnabled()
    finally:
        window.close()
    assert app is not None


def test_dashboard_transcript_preserves_literal_multiline_text(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = SHUDashboard(Settings.from_env({"SHU_DATA_DIR": str(tmp_path)}))
    question = "<a href='https://example.invalid/'>text</a> & symbols"
    answer = "<img src='attachment.png'>\n  Indented শনাক্ত text."
    try:
        window._append_turn("You", question)
        window._append_turn("SHU", answer)

        assert window.transcript.toPlainText() == f"You: {question}\nSHU: {answer}"
        rendered_html = window.transcript.toHtml()
        assert "<a href=" not in rendered_html
        assert "<img src=" not in rendered_html
        assert [turn.content for turn in window.history.recent()] == [question, answer]
    finally:
        window.close()
    assert app is not None


def test_dashboard_stop_only_targets_the_current_voice_session(tmp_path, monkeypatch):
    from weakref import ref

    from app.interface import dashboard

    app = QApplication.instance() or QApplication([])
    window = SHUDashboard(Settings.from_env({"SHU_DATA_DIR": str(tmp_path)}))
    stopped = []

    class FakeAssistant:
        def __init__(self, *, settings, on_turn):
            self.on_turn = on_turn

        def request_stop(self):
            stopped.append(ref(self))

    monkeypatch.setattr(dashboard, "SHUVoiceAssistant", FakeAssistant)
    window._run_worker = lambda _worker, _callback: None
    try:
        window._start_voice()
        first = ref(window._voice_assistant)
        window._voice_finished("")
        assert first() is None

        window._start_voice()
        second = ref(window._voice_assistant)
        window._emergency_stop()
        assert stopped == [second]
        window._voice_finished("")
        assert second() is None
    finally:
        window.close()
    assert app is not None


def test_dashboard_ready_state_does_not_capture_audio_or_start_wake_listener(
    tmp_path, monkeypatch
):
    import sounddevice as sd

    from app.interface import dashboard
    from app.voice import voice_assistant

    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {"SHU_DATA_DIR": str(tmp_path), "SHU_MICROPHONE_DEVICE": ""}
    )

    def unexpected_audio_activity(*_args, **_kwargs):
        raise AssertionError("Idle dashboard must not capture or analyze audio")

    monkeypatch.setattr(sd, "InputStream", unexpected_audio_activity)
    monkeypatch.setattr(sd, "rec", unexpected_audio_activity)
    monkeypatch.setattr(
        voice_assistant, "WakeWordListener", unexpected_audio_activity
    )

    class IdleReminders:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            return []

        def list_pending(self):
            return []

        def shutdown(self, *, wait=True):
            pass

    monkeypatch.setattr(dashboard, "ReminderService", IdleReminders)
    window = SHUDashboard(settings)
    try:
        assert window.status.text().startswith("Ready")
        assert window._voice_assistant is None
        assert not window._chat_progress_timer.isActive()
    finally:
        window.close()
    assert app is not None


def test_dashboard_quiet_mode_applies_to_queued_notifications(tmp_path):
    from threading import Thread

    app = QApplication.instance() or QApplication([])
    window = SHUDashboard(Settings.from_env({"SHU_DATA_DIR": str(tmp_path)}))
    speech_workers = []
    window._run_worker = lambda worker, _callback: speech_workers.append(worker)

    def queue_notification():
        window.reminders.notifier("synthetic", "Take a break", not window.reminders.quiet_mode())

    try:
        assert not window.reminders.quiet_mode()
        worker = Thread(target=queue_notification)
        worker.start()
        worker.join()

        window.quiet_mode.setChecked(True)
        assert window.reminders.quiet_mode()
        app.processEvents()
        assert speech_workers == []

        window.quiet_mode.setChecked(False)
        assert not window.reminders.quiet_mode()
        queue_notification()
        assert len(speech_workers) == 1
        assert speech_workers[0].text == "Take a break"
    finally:
        window.close()


def test_reminder_speech_worker_uses_selected_language_and_reports_success():
    app = QApplication.instance() or QApplication([])

    class FakeTTS:
        def __init__(self):
            self.language = None
            self.text = None

        def set_language(self, language):
            self.language = language

        def speak(self, text):
            self.text = text
            return True

    tts = FakeTTS()
    worker = _ReminderSpeechWorker(tts, "Take a break", "bn")
    result = []
    worker.finished.connect(lambda status, error: result.append((status, error)))
    worker.run()

    assert app is not None
    assert tts.language == "bn"
    assert tts.text == "Take a break"
    assert result == [("spoken", "")]


def test_reminder_speech_worker_reports_tts_error():
    app = QApplication.instance() or QApplication([])

    class FailingTTS:
        def set_language(self, _language):
            pass

        def speak(self, _text):
            raise RuntimeError("device unavailable")

    worker = _ReminderSpeechWorker(FailingTTS(), "Take a break", "en")
    result = []
    worker.finished.connect(lambda status, error: result.append((status, error)))
    worker.run()

    assert app is not None
    assert result == [("", "RuntimeError")]


def test_communication_send_worker_uses_the_reviewed_digest():
    app = QApplication.instance() or QApplication([])

    class FakeService:
        def __init__(self):
            self.call = None

        def send(self, draft_id, *, confirmed, expected_digest):
            self.call = (draft_id, confirmed, expected_digest)
            return "provider-message-id"

    service = FakeService()
    worker = _CommunicationSendWorker(service, "draft-id", "review-digest")
    result = []
    worker.finished.connect(lambda provider_id, error: result.append((provider_id, error)))
    worker.run()

    assert app is not None
    assert service.call == ("draft-id", True, "review-digest")
    assert result == [("provider-message-id", "")]


def test_communication_send_worker_reports_unknown_provider_failure():
    app = QApplication.instance() or QApplication([])

    class FailingService:
        def send(self, *_args, **_kwargs):
            raise TimeoutError("delivery is unknown")

    worker = _CommunicationSendWorker(FailingService(), "draft-id", "review-digest")
    result = []
    worker.finished.connect(lambda provider_id, error: result.append((provider_id, error)))
    worker.run()

    assert app is not None
    assert result == [("", "TimeoutError: delivery is unknown")]


def test_provider_draft_worker_uses_the_reviewed_digest():
    app = QApplication.instance() or QApplication([])

    class FakeService:
        def __init__(self):
            self.call = None

        def save_provider_draft(self, draft_id, *, confirmed, expected_digest):
            self.call = (draft_id, confirmed, expected_digest)
            return "provider-draft-id"

    service = FakeService()
    worker = _ProviderDraftWorker(service, "draft-id", "review-digest")
    result = []
    worker.finished.connect(lambda provider_id, error: result.append((provider_id, error)))
    worker.run()

    assert app is not None
    assert service.call == ("draft-id", True, "review-digest")
    assert result == [("provider-draft-id", "")]


def test_dashboard_mute_control_is_visible_and_reversible(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_MICROPHONE_DEVICE": "",
        }
    )
    window = SHUDashboard(settings)

    class FakeAssistant:
        is_muted = False

        class FakeTTS:
            paused = False

            def pause(self):
                self.paused = True

            def resume(self):
                self.paused = False

        def __init__(self):
            self.tts = self.FakeTTS()

        def set_muted(self, muted):
            self.is_muted = muted

    assistant = FakeAssistant()
    window._voice_assistant = assistant
    window.voice_mute_button.setEnabled(True)
    try:
        window.show()
        window.tabs.setCurrentIndex(2)
        app.processEvents()
        window.reminder_due.setFocus()
        app.processEvents()
        for _ in range(8):
            if app.focusWidget() is window.quiet_mode:
                break
            QTest.keyClick(app.focusWidget(), Qt.Key.Key_Tab)
            app.processEvents()
        assert app.focusWidget() is window.quiet_mode
        QTest.keyClick(window.quiet_mode, Qt.Key.Key_Space)
        assert window.quiet_mode.isChecked()
        QTest.keyClick(window.quiet_mode, Qt.Key.Key_Space)
        assert not window.quiet_mode.isChecked()

        assert window.tabs.count() == 7
        assert window.transcript.accessibleName() == "Conversation transcript"
        assert window.input.accessibleName() == "Message to SHU"
        assert window.memory_table.accessibleName() == "Approved memories"
        assert window.reminder_table.accessibleName() == "Pending reminders"
        assert window.quiet_mode.accessibleName() == "Quiet mode"
        assert "without speaking" in window.quiet_mode.accessibleDescription()
        assert window.stop_button.accessibleName() == "Emergency stop"
        assert "Stop active SHU automation" in window.stop_button.accessibleDescription()
        assert window.voice_activity.accessibleName() == "Voice activity"
        window._voice_activity_received("recording")
        assert window.voice_activity.text() == "Recording microphone"
        window._toggle_voice_mute()
        assert assistant.is_muted
        assert window.voice_mute_button.text() == "Unmute microphone"
        window._voice_activity_received("recording")
        assert window.voice_activity.text() == "Microphone muted"

        window._toggle_voice_mute()
        assert not assistant.is_muted
        assert window.voice_mute_button.text() == "Mute microphone"
        assert window.voice_activity.text() == "Preparing microphone"

        window._voice_activity_received("transcribing")
        assert window.voice_activity.text() == "Transcribing speech"
        window._voice_activity_received("thinking")
        assert window.voice_activity.text() == "Thinking about your request"
        window._voice_activity_received("speech_output")
        assert window.voice_activity.text() == "Preparing or playing speech"

        window.voice_pause_button.setEnabled(True)
        window._toggle_voice_pause()
        assert assistant.tts.paused
        assert window.voice_pause_button.text() == "Resume speech"
        assert window.voice_activity.text() == "Speech paused"
        window._toggle_voice_pause()
        assert not assistant.tts.paused
        assert window.voice_pause_button.text() == "Pause speech"

        window._show_task_progress(2, 2, "verified", "read_value")
        assert window.status.text() == "Task step 2/2: read_value — verified"

        window._set_communication_inputs_enabled(False)
        assert not window.message_recipient.isEnabled()
        assert not window.create_message_button.isEnabled()
        window._set_communication_inputs_enabled(True)
        assert window.message_recipient.isEnabled()
        assert window.create_message_button.isEnabled()
    finally:
        window._voice_assistant = None
        window.close()
    assert app is not None


def test_dashboard_exposes_accessible_barge_in_settings_for_next_voice_session(
    tmp_path,
):
    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_MICROPHONE_DEVICE": "",
        }
    )
    window = SHUDashboard(settings)
    try:
        window.show()
        window.tabs.setCurrentIndex(5)
        app.processEvents()
        window.language_combo.setFocus()
        app.processEvents()
        for _ in range(8):
            if app.focusWidget() is window.voice_barge_in_check:
                break
            QTest.keyClick(app.focusWidget(), Qt.Key.Key_Tab)
            app.processEvents()
        assert app.focusWidget() is window.voice_barge_in_check

        assert not window.voice_barge_in_check.isChecked()
        assert not window.voice_barge_in_rms.isEnabled()
        assert window.voice_barge_in_check.accessibleName() == "Voice barge-in"
        assert "Speaker echo" in window.voice_barge_in_check.accessibleDescription()
        assert (
            window.voice_barge_in_rms.accessibleName()
            == "Voice barge-in RMS threshold"
        )
        assert window.tts_rate.accessibleName() == "Speech rate adjustment"
        assert window.tts_volume.accessibleName() == "Speech output volume"
        assert window.ui_font_size.accessibleName() == "Dashboard text size"
        QTest.keyClick(window.voice_barge_in_check, Qt.Key.Key_Space)
        assert window.voice_barge_in_check.isChecked()
        QTest.keyClick(window.voice_barge_in_check, Qt.Key.Key_Tab)
        assert app.focusWidget() is window.voice_barge_in_rms
        window.voice_barge_in_rms.setValue(0.075)
        window.tts_rate.setValue(15)
        window.tts_volume.setValue(65)
        window.ui_font_size.setValue(14)
        runtime = window._runtime_settings()

        assert window.voice_barge_in_rms.isEnabled()
        assert runtime.voice_barge_in is True
        assert runtime.voice_barge_in_rms == 0.075
        assert runtime.tts_rate_percent == 15
        assert runtime.tts_volume == 0.65
        assert runtime.ui_font_size == 14
        assert window.font().pointSize() == 14
    finally:
        window.close()
    assert app is not None


def test_dashboard_cloud_and_automation_controls_are_independent(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_MICROPHONE_DEVICE": "",
            "SHU_AI_PROVIDER": "google",
            "SHU_CLOUD_AI_ENABLED": "false",
            "SHU_AUTOMATION_ENABLED": "false",
        }
    )
    window = SHUDashboard(settings)
    try:
        assert window.response_style_combo.accessibleName() == "Assistant response style"
        assert window._runtime_settings().response_style == "friendly"
        window.response_style_combo.setCurrentIndex(
            window.response_style_combo.findData("formal")
        )
        assert window._runtime_settings().response_style == "formal"
        assert window.cloud_ai_enabled_check.accessibleName() == "Cloud AI enabled"
        assert window.automation_enabled_check.accessibleName() == "SHU automation enabled"
        assert not window.cloud_ai_enabled_check.isChecked()
        assert not window.automation_enabled_check.isChecked()
        assert not window._runtime_settings().cloud_ai_enabled
        assert not window.registry.automation_enabled
        assert not window.plan_button.isEnabled()

        window.cloud_ai_enabled_check.setChecked(True)
        assert window._runtime_settings().cloud_ai_enabled
        assert window.registry.automation_enabled is False

        window.automation_enabled_check.setChecked(True)
        assert window._runtime_settings().automation_enabled
        assert window.registry.automation_enabled
        assert window.plan_button.isEnabled()

        window.automation_enabled_check.setChecked(False)
        assert not window.registry.automation_enabled
        assert not window.plan_button.isEnabled()
        window.input.setText("synthetic plan request")
        window._plan_task()
        assert not window._task_busy
    finally:
        window.close()
    assert app is not None


def test_dashboard_routes_a_completed_voice_request_to_reviewable_planner(
    tmp_path, monkeypatch
):
    from app.interface import dashboard

    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_MICROPHONE_DEVICE": "",
            "SHU_AUTOMATION_ENABLED": "true",
        }
    )
    window = SHUDashboard(settings)
    request = "Open Calculator"
    workers = []
    previews = []
    created_tasks = []
    try:
        assert window.plan_voice_button.accessibleName() == "Plan last voice request"
        window.input.setText("Keep existing text")
        window._voice_assistant = object()
        window._voice_turn_received(request, "I can prepare a plan for review.")

        assert not window.plan_voice_button.isEnabled()
        assert request in window.transcript.toPlainText()
        window._voice_finished("")
        assert window.plan_voice_button.isEnabled()

        window._run_worker = lambda worker, callback: workers.append((worker, callback))
        window._plan_last_voice_request()

        assert len(workers) == 1
        assert isinstance(workers[0][0], dashboard._PlanWorker)
        assert workers[0][0].request == request
        assert window.input.text() == "Keep existing text"
        assert not window.plan_voice_button.isEnabled()

        window.planner.estimate = lambda _steps: {
            "estimated_duration_seconds": 1,
            "basis": "registered tool default",
        }
        window.planner.create = lambda *args, **kwargs: created_tasks.append(args)
        monkeypatch.setattr(
            QMessageBox,
            "exec",
            lambda message: previews.append(message.text())
            or QMessageBox.StandardButton.No,
        )
        steps_json = json.dumps(
            [{"tool": "list_windows", "arguments": {}}], ensure_ascii=False
        )
        window._plan_finished(steps_json, "")

        assert len(previews) == 1
        assert f"Original request:\n{request}" in previews[0]
        assert steps_json in previews[0]
        assert created_tasks == []
        assert window.planner.list_queued() == []
        assert window.plan_voice_button.isEnabled()
    finally:
        window.close()
    assert app is not None


def test_dashboard_user_controls_have_accessible_labels(tmp_path):
    from PySide6.QtWidgets import (
        QAbstractButton,
        QComboBox,
        QDateTimeEdit,
        QDoubleSpinBox,
        QLineEdit,
        QPlainTextEdit,
        QSpinBox,
        QTableWidget,
        QTextEdit,
    )

    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_MICROPHONE_DEVICE": "",
        }
    )
    window = SHUDashboard(settings)
    widget_types = (
        QAbstractButton,
        QComboBox,
        QDateTimeEdit,
        QDoubleSpinBox,
        QLineEdit,
        QPlainTextEdit,
        QSpinBox,
        QTableWidget,
        QTextEdit,
    )
    missing = []
    checked = 0
    try:
        for widget_type in widget_types:
            for widget in window.findChildren(widget_type):
                # These are Qt's private implementation widgets, not SHU controls.
                if widget.objectName().startswith("qt_"):
                    continue
                checked += 1
                accessible_name = widget.accessibleName().strip()
                if isinstance(widget, QAbstractButton):
                    accessible_name = accessible_name or widget.text().strip()
                elif isinstance(widget, QLineEdit):
                    accessible_name = accessible_name or widget.placeholderText().strip()
                if not accessible_name:
                    missing.append(type(widget).__name__)

        assert checked >= 45
        assert missing == []
    finally:
        window.close()
    assert app is not None


def test_dashboard_task_queue_lists_and_reviews_persisted_plans(tmp_path):
    from app.security.policy import RiskLevel
    from app.security.registry import ToolSpec

    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_MICROPHONE_DEVICE": "",
        }
    )
    window = SHUDashboard(settings)
    calls = []
    window.registry.register(
        ToolSpec(
            name="dashboard_queue_probe",
            description="Read-only queue test probe",
            risk=RiskLevel.READ_ONLY,
            handler=lambda: calls.append("executed"),
            validator=lambda _arguments: {},
        )
    )
    first = window.planner.create(
        "First queued request",
        [{"tool": "dashboard_queue_probe", "arguments": {}}],
    )
    second = window.planner.create(
        "Second queued request",
        [{"tool": "dashboard_queue_probe", "arguments": {}}],
    )
    try:
        window._refresh_task_queue()

        assert window.tabs.count() == 7
        assert window.task_queue_table.rowCount() == 2
        assert window.task_queue_table.item(0, 2).data(Qt.ItemDataRole.UserRole) == first
        assert window.task_queue_table.item(1, 2).data(Qt.ItemDataRole.UserRole) == second
        window.task_queue_table.selectRow(1)
        window._review_selected_queued_task()

        preview = window.task_queue_details.toPlainText()
        assert "Second queued request" in preview
        assert "dashboard_queue_probe" in preview
        assert calls == []
        assert window.planner.preview(first)["status"] == "planned"
        assert window.planner.preview(second)["status"] == "planned"
    finally:
        window.close()
    assert app is not None


def test_dashboard_run_next_requires_plan_confirmation_and_binds_preview(
    tmp_path, monkeypatch
):
    from app.security.policy import RiskLevel
    from app.security.registry import ToolSpec

    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_MICROPHONE_DEVICE": "",
        }
    )
    window = SHUDashboard(settings)
    calls = []
    window.registry.register(
        ToolSpec(
            name="dashboard_queue_modify",
            description="Modify test value",
            risk=RiskLevel.MODIFICATION,
            handler=lambda: calls.append("executed") or "done",
            validator=lambda _arguments: {},
            verifier=lambda value, _arguments: value == "done",
        )
    )
    task_id = window.planner.create(
        "Update test value",
        [{"tool": "dashboard_queue_modify", "arguments": {}}],
    )
    started = []
    preview_formats = []
    window._start_task_worker = lambda passed_id, **kwargs: started.append(
        (passed_id, kwargs)
    )
    try:
        def decline(dialog):
            preview_formats.append(dialog.textFormat())
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "exec", decline)
        window._run_next_queued_task()
        assert started == []
        assert window.planner.preview(task_id)["status"] == "planned"

        def approve(dialog):
            preview_formats.append(dialog.textFormat())
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "exec", approve)
        window._run_next_queued_task()
        assert preview_formats == [Qt.TextFormat.PlainText] * 2
        assert started == [
            (
                task_id,
                {
                    "expected_request": "Update test value",
                    "expected_steps": window.planner.get_steps(task_id),
                },
            )
        ]
        assert calls == []
        assert window.planner.preview(task_id)["status"] == "planned"
    finally:
        window.close()
    assert app is not None


def test_task_worker_passes_reviewed_queue_snapshot():
    app = QApplication.instance() or QApplication([])

    class FakeExecutor:
        def __init__(self):
            self.call = None

        def execute(self, task_id, **kwargs):
            self.call = (task_id, kwargs)
            return {"status": "completed"}

    executor = FakeExecutor()
    expected_steps = [{"tool": "read_value", "arguments": {}}]
    worker = _TaskWorker(
        executor,
        "task-id",
        expected_request="reviewed request",
        expected_steps=expected_steps,
    )
    result = []
    worker.finished.connect(lambda report, error: result.append((report, error)))

    worker.run()

    assert app is not None
    assert executor.call[0] == "task-id"
    assert executor.call[1]["expected_request"] == "reviewed request"
    assert executor.call[1]["expected_steps"] == expected_steps
    assert callable(executor.call[1]["confirm"])
    assert result == [(json.dumps({"status": "completed"}, ensure_ascii=False, indent=2), "")]


def test_dashboard_schedules_overdue_reminder_review_on_startup(tmp_path, monkeypatch):
    from app.interface import dashboard

    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_MICROPHONE_DEVICE": "",
        }
    )
    scheduled = []
    prompted = []

    class FakeReminderService:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            return [{"reminder_id": "overdue-test", "text": "Review reminder"}]

        def list_pending(self):
            return []

        def shutdown(self, *, wait=False):
            pass

    monkeypatch.setattr(dashboard, "ReminderService", FakeReminderService)
    monkeypatch.setattr(
        dashboard.SHUDashboard,
        "_ask_overdue",
        lambda _self, reminder: prompted.append(reminder["reminder_id"]),
    )
    monkeypatch.setattr(
        dashboard.QTimer,
        "singleShot",
        lambda delay, callback: scheduled.append((delay, callback)),
    )

    window = SHUDashboard(settings)
    try:
        assert len(scheduled) == 1
        delay, callback = scheduled.pop()
        assert delay == 500
        assert prompted == []

        callback()
        assert prompted == ["overdue-test"]
    finally:
        window.close()
    assert app is not None


def test_dashboard_closes_without_blocking_the_ui_while_two_workers_finish(
    tmp_path, monkeypatch
):
    from threading import Event
    from time import monotonic, sleep

    from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env({"SHU_DATA_DIR": str(tmp_path)})
    window = SHUDashboard(settings)
    started = [Event(), Event()]
    release = [Event(), Event()]
    waits = []
    stops = []
    alerts = []
    ui_events = []

    class BlockingWorker(QObject):
        finished = Signal(str, str)

        def __init__(self, index):
            super().__init__()
            self.index = index

        @Slot()
        def run(self):
            started[self.index].set()
            release[self.index].wait(timeout=10)
            self.finished.emit("", "late plan result")

    def wait_until(predicate):
        deadline = monotonic() + 4
        while not predicate() and monotonic() < deadline:
            app.processEvents()
            sleep(0.01)
        assert predicate()

    thread_wait = QThread.wait

    def record_wait(thread, milliseconds):
        waits.append(milliseconds)
        return thread_wait(thread, milliseconds)

    monkeypatch.setattr(QThread, "wait", record_wait)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: alerts.append(args))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: alerts.append(args))
    monkeypatch.setattr(window.tray, "isVisible", lambda: False)
    window.emergency_stop.add_callback(lambda: stops.append("stop"))
    window.show()
    try:
        for index in range(2):
            window._run_worker(BlockingWorker(index), window._plan_finished)
        wait_until(lambda: all(event.is_set() for event in started))
        QTimer.singleShot(0, lambda: ui_events.append("responsive"))

        assert not window.close()
        assert waits == []
        assert window.isVisible()
        assert not window.tabs.isEnabled()
        assert not window.menuBar().isEnabled()
        assert not window.close()
        assert stops == ["stop"]
        assert window.emergency_stop.is_stopped

        window._start_voice()
        window._show_notification("synthetic-id", "Closing reminder", True)
        window._ask_overdue({"reminder_id": "synthetic-id", "text": "Closing reminder"})
        assert window.status.text().endswith("Reminder: Closing reminder")
        assert window._voice_assistant is None
        assert not window._reminder_speech_active
        assert len(window._threads) == 2
        assert window.emergency_stop.is_stopped
        wait_until(lambda: bool(ui_events))

        release[0].set()
        wait_until(lambda: len(window._threads) == 1)
        assert window.isVisible()
        assert alerts == []

        release[1].set()
        wait_until(lambda: not window.isVisible())
        assert not window._threads
        assert waits and all(wait == 0 for wait in waits)
        assert stops == ["stop"]
        assert alerts == []
    finally:
        for event in release:
            event.set()
        wait_until(lambda: not window._threads)
        window.close()


def test_dashboard_resolves_local_whatsapp_contact_before_preview(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_MICROPHONE_DEVICE": "",
        }
    )
    window = SHUDashboard(settings)
    try:
        contact = window.contacts.add("Maya Das", "+919876543210", confirmed=True)
        service = CommunicationService(window.database)
        window._communications = service
        window.message_channel.setCurrentIndex(
            window.message_channel.findData("whatsapp")
        )
        window.message_recipient.setText("maya das")
        window.message_body.setPlainText("Hello from SHU")

        window._create_message_draft()

        assert window.message_recipient.text() == contact.phone_e164
        assert "Maya Das (+919876543210)" in window.message_preview.toPlainText()
        assert service.preview(window._active_message_draft_id).recipient == contact.phone_e164
        assert window.send_message_button.isEnabled()
    finally:
        window.close()
    assert app is not None


@pytest.mark.parametrize(
    ("operation", "worker_type"),
    [("_save_provider_email_draft", _ProviderDraftWorker), ("_send_message_draft", _CommunicationSendWorker)],
)
@pytest.mark.parametrize("invalidate_during_review", [False, True])
def test_dashboard_message_confirmation_shows_and_binds_exact_draft(
    tmp_path, monkeypatch, operation, worker_type, invalidate_during_review
):
    app = QApplication.instance() or QApplication([])
    window = SHUDashboard(Settings.from_env({"SHU_DATA_DIR": str(tmp_path)}))
    attachment = tmp_path / "minutes.txt"
    attachment.write_text("Meeting notes", encoding="utf-8")
    service = CommunicationService(window.database, attachment_roots=(tmp_path,))
    window._communications = service
    body = "Keep the markup literal: <b>ready</b> & checked.\nSecond line."
    draft = service.create_draft("email", "test@example.invalid", body, attachments=[attachment])
    digest = service.preview(draft).digest
    window._active_message_draft_id = draft
    window._active_message_digest = digest
    workers = []
    window._run_worker = lambda worker, _callback: workers.append(worker)

    def confirm(dialog):
        assert dialog.textFormat() == Qt.TextFormat.PlainText
        assert body in dialog.text()
        assert "test@example.invalid" in dialog.text()
        assert "minutes.txt" in dialog.text()
        assert dialog.defaultButton() is dialog.button(QMessageBox.StandardButton.No)
        if invalidate_during_review:
            window.message_body.setPlainText("An edited draft")
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "exec", confirm)
    try:
        getattr(window, operation)()
        assert service.status(draft) == "draft"
        if invalidate_during_review:
            assert workers == []
            assert "draft changed" in window.status.text()
        else:
            assert len(workers) == 1
            assert isinstance(workers[0], worker_type)
            assert (workers[0].draft_id, workers[0].digest) == (draft, digest)
    finally:
        window.close()
    assert app is not None


def test_dashboard_manual_reminder_saves_qt_instant_and_displays_saved_zone(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = SHUDashboard(Settings.from_env({"SHU_DATA_DIR": str(tmp_path)}))
    zone_name = "America/New_York"
    picked = (datetime.now(timezone.utc) + timedelta(days=10)).replace(second=0, microsecond=0)
    qt_zone = QTimeZone(zone_name.encode("ascii"))
    monkeypatch.setattr(QTimeZone, "systemTimeZoneId", staticmethod(lambda: qt_zone.id()))
    try:
        window.reminder_due.setTimeZone(qt_zone)
        window.reminder_due.setDateTime(QDateTime.fromMSecsSinceEpoch(int(picked.timestamp() * 1000), qt_zone))
        window.reminder_text.setText("Review the minutes")
        window._add_reminder()

        row, = window.reminders.list_pending()
        assert row["timezone"] == zone_name
        assert datetime.fromisoformat(row["due_at"]) == picked
        assert window.reminder_table.item(0, 0).text() == (
            picked.astimezone(ZoneInfo(zone_name)).strftime("%Y-%m-%d %H:%M:%S %z")
        )
    finally:
        window.close()
    assert app is not None


def test_dashboard_reminder_refuses_unknown_system_time_zone(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = SHUDashboard(Settings.from_env({"SHU_DATA_DIR": str(tmp_path)}))
    messages = []
    monkeypatch.setattr(QTimeZone, "systemTimeZoneId", staticmethod(lambda: b""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[-1]))
    try:
        window.reminder_text.setText("Review the minutes")
        window.reminder_natural.setText("Take a break in 2 hours")
        window._add_reminder()
        window._add_natural_reminder()

        assert not window.reminders.list_pending()
        assert len(messages) == 2
        assert all("local time zone is unavailable" in message for message in messages)
    finally:
        window.close()
    assert app is not None
