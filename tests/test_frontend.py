"""Frontend bridge uses isolated data and the existing policy controller."""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl

from app.config import Settings
from app.interface.frontend import (
    DesktopBridge,
    RuntimeController,
    LocalResources,
    LocalPage,
    DIST,
)


@pytest.fixture
def bridge(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = RuntimeController(Settings.from_env({"SHU_DATA_DIR": str(tmp_path)}))
    result = DesktopBridge(controller)
    yield result
    result.timer.stop()
    controller.shutting_down = True
    controller.close()
    app.processEvents()


def test_empty_frontend_has_no_demo_records(bridge):
    state = bridge.snapshot()
    assert state["transcript"] == state["memories"] == state["workflows"] == []
    assert state["settings"]["localModel"] == "qwen2.5:1.5b"
    assert "api_key" not in bridge.read()


def test_frontend_reads_actual_memory(bridge):
    record = bridge.controller.memories.add_memory(
        "Synthetic garden preference", approved=True
    )
    assert bridge.snapshot()["memories"][0]["id"] == record.memory_id


def test_frontend_stop_resume_reaches_controller(bridge):
    bridge.dispatch("stop", "{}")
    assert bridge.controller.emergency_stop.is_stopped
    assert bridge.snapshot()["assistantState"] == "stopped"
    bridge.dispatch("resume", "{}")
    assert not bridge.controller.emergency_stop.is_stopped


@pytest.mark.parametrize(
    "action,payload", [("shell.exec", "{}"), ("chat", "[]"), ("chat", "not-json")]
)
def test_bridge_rejects_invalid_actions_without_work(bridge, action, payload):
    bridge.dispatch(action, payload)
    assert not bridge.controller._threads
    assert bridge.controller.status.text().startswith("Action failed:")


def test_native_controls_close_does_not_stop_frontend(bridge):
    bridge.controller.close()
    assert not bridge.controller._closing


def test_editing_draft_invalidates_review(bridge):
    bridge.controller._active_message_draft_id = "fixture"
    bridge.dispatch("invalidate_draft", "{}")
    assert bridge.controller._active_message_draft_id is None


def test_voice_pause_and_resume_reach_playback_without_recording(bridge):
    calls = []
    controller = bridge.controller
    controller._voice_assistant = SimpleNamespace(
        tts=SimpleNamespace(
            pause=lambda: calls.append("pause"), resume=lambda: calls.append("resume")
        )
    )
    controller._voice_stage = "speech_output"
    controller.voice_pause_button.setEnabled(True)
    try:
        bridge.dispatch("pause_speech", "{}")
        state = bridge.snapshot()
        assert calls == ["pause"]
        assert state["speechPaused"] is True
        assert state["voiceActivity"] == "Speech paused"
        bridge.dispatch("pause_speech", "{}")
        assert calls == ["pause", "resume"]
        assert not bridge.snapshot()["speechPaused"]
    finally:
        controller._voice_assistant = None


@pytest.mark.parametrize(
    "blocked_by", ["active_voice", "automation", "stop", "task_busy", "no_request"]
)
def test_voice_plan_requires_an_eligible_finished_session(
    bridge, monkeypatch, blocked_by
):
    controller = bridge.controller
    controller.registry.set_automation_enabled(True)
    controller._last_voice_request = "Synthetic voice request"
    if blocked_by == "active_voice":
        controller._voice_assistant = object()
    if blocked_by == "automation":
        controller.registry.set_automation_enabled(False)
    if blocked_by == "stop":
        controller.emergency_stop.trigger()
    if blocked_by == "task_busy":
        controller._task_busy = True
    if blocked_by == "no_request":
        controller._last_voice_request = None
    controller._update_voice_plan_button()
    monkeypatch.setattr(
        controller,
        "_request_task_plan",
        lambda *a, **k: pytest.fail("Planning must remain blocked"),
    )
    try:
        assert not bridge.snapshot()["canPlanVoice"]
        bridge.dispatch("plan_voice", "{}")
        assert controller.status.text().startswith("Action failed:")
    finally:
        controller._voice_assistant = None
        controller._task_busy = False


def test_voice_plan_uses_original_recognized_text(bridge, monkeypatch):
    controller = bridge.controller
    controller.registry.set_automation_enabled(True)
    controller._last_voice_request = "Synthetic original voice request"
    controller._update_voice_plan_button()
    requests = []
    monkeypatch.setattr(
        controller,
        "_request_task_plan",
        lambda request, **kwargs: requests.append((request, kwargs)),
    )
    assert bridge.snapshot()["canPlanVoice"]
    bridge.dispatch(
        "plan_voice", json.dumps({"text": "Must not replace recognized request"})
    )
    assert requests == [("Synthetic original voice request", {"from_voice": True})]


def test_idle_voice_controls_do_not_start_capture_or_planning(bridge, monkeypatch):
    monkeypatch.setattr(
        bridge.controller,
        "_toggle_voice_pause",
        lambda: pytest.fail("No speech session"),
    )
    state = bridge.snapshot()
    assert not state["canPauseSpeech"]
    assert not state["canPlanVoice"]
    bridge.dispatch("pause_speech", "{}")
    assert bridge.controller._voice_assistant is None
    assert not bridge.controller._threads


@pytest.mark.parametrize("approved", [False, True])
def test_memory_save_requires_native_review(bridge, monkeypatch, approved):
    reviewed = []

    def confirm(title, content):
        reviewed.append(content)
        return approved

    monkeypatch.setattr(bridge, "confirm", confirm)
    bridge.dispatch(
        "save_memory",
        json.dumps({"type": "Preference", "content": "Synthetic garden preference"}),
    )
    assert reviewed == ["Synthetic garden preference"]
    assert len(bridge.snapshot()["memories"]) == int(approved)


def test_memory_correction_rejects_changes_after_review(bridge, monkeypatch):
    store = bridge.controller.memories
    record = store.add_memory("Original synthetic memory", approved=True)

    def confirm(title, preview):
        assert "Original synthetic memory" in preview
        assert "Proposed synthetic correction" in preview
        store.update_memory(
            record.memory_id, "Concurrent synthetic edit", approved=True
        )
        return True

    monkeypatch.setattr(bridge, "confirm", confirm)
    bridge.dispatch(
        "correct_memory",
        json.dumps(
            {"id": record.memory_id, "content": "Proposed synthetic correction"}
        ),
    )
    assert store.get_memory(record.memory_id).content == "Concurrent synthetic edit"
    assert bridge.controller.status.text().startswith("Action failed:")


def test_contact_add_and_delete_use_actual_local_store(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "confirm", lambda *args: True)
    bridge.dispatch(
        "add_contact",
        json.dumps({"name": "Synthetic contact", "phone": "+12025550123"}),
    )
    contact = bridge.snapshot()["whatsappContacts"][0]
    assert contact["name"] == "Synthetic contact"
    bridge.dispatch("delete_contact", json.dumps({"id": contact["id"]}))
    assert bridge.snapshot()["whatsappContacts"] == []


def test_text_preview_cannot_inherit_native_template_mode(bridge, monkeypatch):
    c = bridge.controller
    c.message_channel.setCurrentIndex(1)
    c.message_type.setCurrentIndex(1)
    observed = []
    monkeypatch.setattr(
        c,
        "_create_message_draft",
        lambda: observed.append(c.message_type.currentData()),
    )
    bridge.dispatch(
        "preview",
        json.dumps(
            {
                "channel": "WhatsApp",
                "recipient": "+12025550123",
                "message": "Synthetic draft",
            }
        ),
    )
    assert observed == ["text"]


def test_busy_bridge_allows_emergency_stop_but_blocks_mutations(bridge, monkeypatch):
    bridge.busy = True
    monkeypatch.setattr(
        bridge, "confirm", lambda *args: pytest.fail("No nested approval permitted")
    )
    bridge.dispatch("save_memory", '{"content":"nested"}')
    bridge.dispatch("stop", "{}")
    assert bridge.controller.emergency_stop.is_stopped
    assert bridge.snapshot()["memories"] == []


@pytest.mark.parametrize(
    "target,allowed",
    [
        (QUrl.fromLocalFile(str(DIST / "index.html")), True),
        (QUrl.fromLocalFile(str(DIST / "assets" / "app.js")), True),
        (QUrl.fromLocalFile(str(DIST.parent.parent / ".env")), False),
        (QUrl("https://example.com/script.js"), False),
        (QUrl("http://localhost:8000/"), False),
        (QUrl("qrc:///qtwebchannel/qwebchannel.js"), True),
    ],
)
def test_frontend_resources_are_local_and_confined(target, allowed):
    class Request:
        blocked = None

        def requestUrl(self):
            return target

        def block(self, value):
            self.blocked = value

    request = Request()
    LocalResources().interceptRequest(request)
    assert request.blocked is not allowed


def test_only_dashboard_document_can_navigate():
    assert LocalPage.acceptNavigationRequest(
        None, QUrl.fromLocalFile(str(DIST / "index.html")), None, True
    )
    assert not LocalPage.acceptNavigationRequest(
        None, QUrl("https://example.com"), None, True
    )
    assert not LocalPage.acceptNavigationRequest(
        None, QUrl.fromLocalFile(str(DIST / "other.html")), None, True
    )


@pytest.mark.parametrize("action", ["send", "save_draft"])
def test_message_actions_cannot_bypass_disabled_native_controls(
    bridge, monkeypatch, action
):
    method = "_send_message_draft" if action == "send" else "_save_provider_email_draft"
    monkeypatch.setattr(
        bridge.controller, method, lambda: pytest.fail("No reviewed draft")
    )
    bridge.dispatch(action, "{}")
    assert bridge.controller.status.text().startswith("Action failed:")
