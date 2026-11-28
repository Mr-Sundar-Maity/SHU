"""Local React shell over the existing, approval-gated desktop controller.

No HTTP listener, browser speech service, or frontend credentials are used.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot, Qt, QDateTime
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from app.interface.dashboard import SHUDashboard

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class LocalResources(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        url = info.requestUrl()
        allowed = url.scheme() in {"qrc", "data", "blob"}
        if url.isLocalFile():
            allowed = Path(url.toLocalFile()).resolve().is_relative_to(DIST.resolve())
        info.block(not allowed)


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, kind, main_frame):
        return (
            url.isLocalFile()
            and Path(url.toLocalFile()).resolve() == (DIST / "index.html").resolve()
        )


class DesktopBridge(QObject):
    changed = Signal(str)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.entries = []
        self.entry_sequence = 0
        self.last_snapshot = ""
        self.busy = False
        original = controller._append_turn

        def append(speaker, text):
            original(speaker, text)
            self.entry_sequence += 1
            self.entries.append(
                dict(
                    id=str(self.entry_sequence),
                    role="user" if speaker == "You" else "assistant",
                    text=text,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    mode="voice" if controller._voice_assistant else "direct",
                )
            )
            self.entries = self.entries[-100:]

        controller._append_turn = append
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.publish)
        self.timer.start(500)

    def snapshot(self):
        c = self.controller
        assistant_state = "ready"
        if c._voice_assistant:
            assistant_state = {
                "speech_output": "speaking",
                "transcribing": "thinking",
                "thinking": "thinking",
            }.get(c._voice_stage, "listening")
        if c._chat_busy or c._task_busy:
            assistant_state = "thinking"
        if c.emergency_stop.is_stopped:
            assistant_state = "stopped"
        workflows = []
        for row in c.learning.procedures.list_all():
            steps = json.loads(row["steps_json"])
            workflows.append(
                dict(
                    id=row["procedure_id"],
                    name=row["name"],
                    status={"approved": "Approved", "revoked": "Revoked"}.get(
                        row["approval_status"], "Pending approval"
                    ),
                    tools=[s["tool"] for s in steps],
                    steps=[json.dumps(s, ensure_ascii=False) for s in steps],
                    lastPreview="",
                )
            )
        return dict(
            transcript=self.entries,
            statusBanner=c.status.text(),
            assistantState=assistant_state,
            isListening=c._voice_assistant is not None,
            isMuted=c._voice_muted,
            voiceActivity=c.voice_activity.text(),
            speechPaused=c._voice_speech_paused,
            canPauseSpeech=c.voice_pause_button.isEnabled(),
            canPlanVoice=c.plan_voice_button.isEnabled(),
            quietMode=c.quiet_mode.isChecked(),
            memories=[
                dict(
                    id=m.memory_id,
                    type="Preference" if m.memory_type == "preference" else "Fact",
                    content=m.content,
                    approved=True,
                    updatedAt=m.updated_at,
                )
                for m in c.memories.list_memories()
            ],
            whatsappContacts=[
                dict(id=r.contact_id, name=r.display_name, phone=r.phone_e164)
                for r in c.contacts.list_contacts()
            ],
            reminders=[
                dict(
                    id=r["reminder_id"],
                    due=r["due_at"],
                    reminder=r["text"],
                    status="Scheduled",
                    quietMode=c.quiet_mode.isChecked(),
                )
                for r in c.reminders.list_pending()
            ],
            workflows=workflows,
            workflowPreviewText=c.workflow_details.toPlainText(),
            settings=dict(
                voiceLanguage=c.language_combo.currentText(),
                provider=c.provider_combo.currentText(),
                microphone=c.mic_combo.currentText(),
                dataFolder=str(c.settings.data_dir),
                localModel=c.settings.local_ai_model,
                emergencyHotkey="Ctrl+Alt+Pause",
                bridgeUrl="Qt WebChannel (local process)",
                colorTheme="frost-blue",
            ),
            preview=c.message_preview.toPlainText(),
            hasLastTask=c.feedback_button.isEnabled(),
            canSendDraft=c.send_message_button.isEnabled(),
            canSaveDraft=c.save_provider_draft_button.isEnabled(),
        )

    @Slot(result=str)
    def read(self):
        return json.dumps(self.snapshot(), ensure_ascii=False)

    def publish(self):
        if self.controller._closing:
            return
        raw = self.read()
        if raw != self.last_snapshot:
            self.last_snapshot = raw
            self.changed.emit(raw)

    @Slot(str, str)
    def dispatch(self, action, raw):
        c = self.controller
        if c._closing or len(raw) > 64000:
            return
        if self.busy:
            if action == "stop":
                c._emergency_stop()
            return
        self.busy = True
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Invalid request")
            simple = {
                "stop": c._emergency_stop,
                "mute": c._toggle_voice_mute,
                "listen": c._start_voice,
                "stop_voice": c._stop_active_voice,
                "pause_speech": c._toggle_voice_pause,
                "plan_voice": c._plan_last_voice_request,
                "diagnostics": c._show_diagnostics,
                "reset": c._reset_conversation,
                "memory_add": c._add_memory,
                "memory_export": c._export_memories,
                "memory_review": c._review_memories,
                "contacts": c._manage_contacts,
                "rate": c._rate_last_task,
                "send": c._send_message_draft,
                "save_draft": c._save_provider_email_draft,
                "natural_reminder": c._add_natural_reminder,
            }
            if action in {"save_memory", "correct_memory"}:
                content = str(data.get("content", "")).strip()
                if not content:
                    raise ValueError("Empty memory")
                current = (
                    c.memories.get_memory(str(data.get("id", "")))
                    if action == "correct_memory"
                    else None
                )
                preview = (
                    "Current memory:\n" + current.content + "\n\nReplacement:\n"
                    if current
                    else ""
                ) + content
                if self.confirm("Approve memory", preview):
                    if current is None:
                        c.memories.add_memory(
                            content,
                            memory_type=(
                                "preference"
                                if data.get("type") == "Preference"
                                else "long_term"
                            ),
                            approved=True,
                        )
                    else:
                        c.memories.update_memory(
                            current.memory_id,
                            content,
                            approved=True,
                            expected_record=current,
                        )
                    c._refresh_memories()
            elif action == "add_reminder":
                selected = QDateTime.fromString(
                    str(data.get("due", "")).replace("T", " "), "yyyy-MM-dd HH:mm"
                )
                if not selected.isValid():
                    raise ValueError("Invalid reminder time")
                c.reminder_text.setText(str(data.get("text", "")))
                c.reminder_due.setDateTime(selected)
                c._add_reminder()
            elif action == "add_contact":
                name, phone = str(data.get("name", "")), str(data.get("phone", ""))
                if self.confirm("Add local contact", name + "\n" + phone):
                    c.contacts.add(name, phone, confirmed=True)
            elif action == "delete_contact":
                record = c.contacts.get(str(data.get("id", "")))
                if record and self.confirm(
                    "Delete local contact",
                    str(record.display_name) + "\n" + record.phone_e164,
                ):
                    c.contacts.delete(record.contact_id, confirmed=True)
            elif action in simple:
                if action == "pause_speech" and not c.voice_pause_button.isEnabled():
                    raise ValueError("No active speech session")
                if action == "plan_voice" and not c.plan_voice_button.isEnabled():
                    raise ValueError("No eligible voice request to plan")
                if action == "send" and not c.send_message_button.isEnabled():
                    raise ValueError("Sending requires a fresh reviewed draft")
                if (
                    action == "save_draft"
                    and not c.save_provider_draft_button.isEnabled()
                ):
                    raise ValueError("Saving requires a fresh reviewed email draft")
                if action == "natural_reminder":
                    c.reminder_natural.setText(str(data.get("text", "")))
                simple[action]()
                if (
                    action == "reset"
                    and not c._chat_busy
                    and c._voice_assistant is None
                ):
                    self.entries.clear()
            elif action in {"chat", "plan"}:
                c.input.setText(str(data.get("text", "")))
                (c._send_text if action == "chat" else c._plan_task)()
            elif action == "resume":
                c.emergency_stop.reset()
                c.status.setText("Ready")
            elif action == "quiet":
                c.quiet_mode.setChecked(bool(data.get("enabled")))
            elif action == "invalidate_draft":
                c._invalidate_message_preview()
            elif action == "refresh":
                c._refresh_memories()
                c._refresh_reminders()
                c._refresh_workflows()
            elif action == "controls":
                index = {
                    "memory": 1,
                    "reminders": 2,
                    "communications": 3,
                    "workflows": 4,
                    "settings": 5,
                    "tasks": 6,
                }.get(data.get("tab"), 0)
                c.tabs.setCurrentIndex(index)
                c.show()
                c.raise_()
            elif action == "preview":
                if not c.message_body.isEnabled():
                    raise ValueError("Wait for the current message operation")
                c.message_channel.setCurrentIndex(
                    0 if data.get("channel") == "Email" else 1
                )
                c.message_type.setCurrentIndex(0)
                c.message_recipient.setText(str(data.get("recipient", "")))
                c.message_subject.setText(str(data.get("subject", "")))
                c.message_body.setPlainText(str(data.get("message", "")))
                c._create_message_draft()
            elif action.startswith(("memory_", "reminder_", "workflow_")):
                group, verb = action.split("_", 1)
                table = {
                    "memory": c.memory_table,
                    "reminder": c.reminder_table,
                    "workflow": c.workflow_table,
                }[group]
                operations = {
                    "memory_edit": c._edit_memory,
                    "memory_delete": c._delete_memory,
                    "reminder_snooze": c._snooze_reminder,
                    "reminder_complete": c._complete_reminder,
                    "reminder_cancel": c._cancel_reminder,
                    "workflow_review": c._review_workflow,
                    "workflow_edit": c._edit_workflow,
                    "workflow_approve": c._approve_workflow,
                    "workflow_revoke": c._revoke_workflow,
                    "workflow_replay": c._replay_workflow,
                }
                operation = operations[action]
                for row in range(table.rowCount()):
                    if table.item(row, 2).text() == data.get("id"):
                        table.selectRow(row)
                        operation()
                        break
                else:
                    raise ValueError(
                        "Record no longer exists; refresh and review it again"
                    )
            else:
                raise ValueError("Unsupported desktop action")
        except Exception as error:
            c.status.setText("Action failed: " + type(error).__name__)
        finally:
            self.busy = False
        self.publish()

    def confirm(self, title, text):
        dialog = QMessageBox(self.controller)
        dialog.setWindowTitle(title)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(text)
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        return dialog.exec() == QMessageBox.StandardButton.Yes


class RuntimeController(SHUDashboard):
    shutting_down = False

    def closeEvent(self, event):
        if not self.shutting_down:
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)


class FrontendWindow(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.controller = RuntimeController(settings)
        self.setWindowTitle("SHU")
        self.resize(1440, 900)
        self.profile = QWebEngineProfile(self)
        self.interceptor = LocalResources(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.view = QWebEngineView(self)
        self.page = LocalPage(self.profile, self.view)
        self.view.setPage(self.page)
        self.channel = QWebChannel(self.page)
        self.bridge = DesktopBridge(self.controller)
        self.channel.registerObject("shu", self.bridge)
        self.page.setWebChannel(self.channel)
        self.setCentralWidget(self.view)
        self.view.setUrl(QUrl.fromLocalFile(str(DIST / "index.html")))
        self.controller.activate_emergency_hotkey()

    def closeEvent(self, event):
        self.controller.shutting_down = True
        self.controller.close()
        if self.controller._threads:
            event.ignore()
            QTimer.singleShot(200, self.close)
        else:
            self.bridge.timer.stop()
            event.accept()


def main():
    if not (DIST / "index.html").is_file():
        print("Build the dashboard first: cd frontend; npm ci; npm run build")
        return 1
    app = QApplication.instance() or QApplication(sys.argv)
    window = FrontendWindow()
    window.show()
    return app.exec()
