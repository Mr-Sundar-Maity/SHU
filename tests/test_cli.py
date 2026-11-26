import json
from types import SimpleNamespace
import pytest

from app.cli import (
    build_parser,
    communication_send,
    communication_save_provider_draft,
    configure_console_encoding,
    communication_draft,
    contacts_add,
    email_auth,
    email_related_action,
    mic_check,
    resolve_whatsapp_recipient,
    voice_chat,
)
from app.applications.contacts import ContactBook
from app.applications.communications import DeliveryOutcomeUnknown
from database.database import Database


def test_console_encoding_uses_utf8_when_stream_supports_reconfigure(monkeypatch):
    calls = []

    class Stream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("app.cli.sys.stdout", Stream())
    monkeypatch.setattr("app.cli.sys.stderr", Stream())

    configure_console_encoding()

    assert calls == [
        {"encoding": "utf-8", "errors": "replace"},
        {"encoding": "utf-8", "errors": "replace"},
    ]


@pytest.mark.parametrize("clear", [False, True])
@pytest.mark.parametrize("concurrent_correction", [False, True])
def test_memory_retention_preserves_a_concurrent_content_correction(
    tmp_path, monkeypatch, capsys, clear, concurrent_correction,
):
    from datetime import datetime, timedelta, timezone
    from app import cli
    from memory.memory_manager import MemoryManager

    database = Database(tmp_path / "memory-retention.db")
    database.initialize()
    manager = MemoryManager(database)
    other = MemoryManager(Database(database.path))
    old_deadline = datetime.now(timezone.utc) + timedelta(days=1)
    original = manager.add_memory("Original garden note", approved=True, retention_until=old_deadline)
    new_deadline = datetime.now(timezone.utc) + timedelta(days=2)
    read_memory = manager.get_memory

    def read_then_correct(memory_id):
        reviewed = read_memory(memory_id)
        if concurrent_correction:
            other.update_memory(memory_id, "Concurrent correction", approved=True)
        return reviewed

    monkeypatch.setattr(cli, "_database", lambda: database)
    monkeypatch.setattr(cli, "MemoryManager", lambda _database: manager)
    monkeypatch.setattr(manager, "get_memory", read_then_correct)
    result = cli.memory_retention(original.memory_id, new_deadline.isoformat(), clear=clear, confirmed=True)
    saved = other.get_memory(original.memory_id)
    if concurrent_correction:
        assert result == 1
        assert saved.content == "Concurrent correction"
        assert saved.retention_until == original.retention_until
        assert "changed since review" in capsys.readouterr().out
    else:
        assert result == 0
        assert saved.content == original.content
        assert saved.retention_until == (None if clear else new_deadline.isoformat(timespec="microseconds"))
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 2


def test_provider_draft_command_requires_a_digest_and_confirmation_flag():
    args = build_parser().parse_args(
        [
            "comms",
            "save-provider-draft",
            "draft-id",
            "--digest",
            "review-digest",
            "--confirm",
        ]
    )

    assert args.comms_action == "save-provider-draft"
    assert args.draft_id == "draft-id"
    assert args.digest == "review-digest"
    assert args.confirm


@pytest.mark.parametrize("confirmation", ["yes", "YES", "Yes"])
def test_credential_set_accepts_case_insensitive_yes_without_echoing_token(
    monkeypatch, capsys, confirmation
):
    from app.cli import credential_set

    token_value = "synthetic-test-token"
    answers = iter([token_value, token_value])
    saved = []
    monkeypatch.setattr("app.cli.getpass.getpass", lambda _prompt: next(answers))
    monkeypatch.setattr("builtins.input", lambda _prompt: confirmation)
    monkeypatch.setattr(
        "app.cli.WindowsCredentialStore.set",
        lambda _self, name, secret, *, approved: saved.append((name, secret, approved)),
    )

    assert credential_set("whatsapp_cloud_api_access_token") == 0
    assert saved == [("whatsapp_cloud_api_access_token", token_value, True)]
    output = capsys.readouterr().out
    assert "Credential stored in Windows Credential Manager." in output
    assert token_value not in output


def test_text_chat_marks_retrieved_memory_sensitive(monkeypatch, tmp_path):
    from app import cli
    from app.config import Settings

    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path),
            "SHU_AI_PROVIDER": "google",
            "SHU_RESPONSE_STYLE": "serious",
        }
    )
    memory_message = {
        "role": "user",
        "content": "APPROVED MEMORY DATA: prefers the blue theme",
    }
    calls = []

    class FakeAI:
        def __init__(self, _settings):
            pass

        def ask(self, question, **kwargs):
            calls.append((question, kwargs))
            return "Response"

    class FakeRetriever:
        def context_messages(self, _question):
            return [memory_message]

    database = SimpleNamespace(path=SimpleNamespace(exists=lambda: True))
    answers = iter(["What preference did I save?", "/quit"])
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "SHUAIEngine", FakeAI)
    monkeypatch.setattr(cli, "_database", lambda: database)
    monkeypatch.setattr(cli, "MemoryManager", lambda _database: object())
    monkeypatch.setattr(cli, "MemoryRetriever", lambda _manager: FakeRetriever())
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert cli.text_chat(provider="google") == 0
    question, kwargs = calls[0]
    assert question == "What preference did I save?"
    assert kwargs["sensitive"] is True
    assert memory_message in kwargs["context"]
    assert "direct, sober, professional wording" in kwargs["system_instruction"]


@pytest.mark.parametrize("reset_command", ["/reset", "/clear"])
def test_text_chat_reset_clears_recent_context_without_deleting_memories(
    monkeypatch, tmp_path, capsys, reset_command
):
    from app import cli
    from app.config import Settings

    settings = Settings.from_env({"SHU_DATA_DIR": str(tmp_path)})
    calls = []

    class FakeAI:
        def __init__(self, _settings):
            pass

        def ask(self, question, **kwargs):
            calls.append((question, kwargs["context"]))
            return "test reply"

    database = SimpleNamespace(path=SimpleNamespace(exists=lambda: False))
    answers = iter(["First question", reset_command, "Second question", "/quit"])
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "SHUAIEngine", FakeAI)
    monkeypatch.setattr(cli, "_database", lambda: database)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert cli.text_chat(provider="ollama") == 0

    assert calls == [("First question", []), ("Second question", [])]
    output = capsys.readouterr().out
    assert "Recent conversation context cleared" in output
    assert "Approved saved memories were not changed" in output


def test_browser_read_accepts_an_explicit_installed_browser_channel():
    args = build_parser().parse_args(
        ["browser", "read", "https://example.com", "--channel", "msedge"]
    )

    assert args.command == "browser"
    assert args.browser_action == "read"
    assert args.url == "https://example.com"
    assert args.channel == "msedge"


def test_cli_task_services_respect_startup_automation_switch(monkeypatch, tmp_path):
    from app.cli import _task_services

    monkeypatch.setenv("SHU_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SHU_AUTOMATION_ENABLED", "false")

    _planner, executor = _task_services()

    assert executor.registry.automation_enabled is False


def test_browser_session_parser_accepts_a_browser_channel():
    args = build_parser().parse_args(["browser", "session", "--channel", "chrome"])

    assert args.command == "browser"
    assert args.browser_action == "session"
    assert args.channel == "chrome"


def test_files_cli_previews_and_copies_only_after_typed_yes(monkeypatch, tmp_path, capsys):
    from app.cli import file_copy, file_preview

    monkeypatch.setenv("SHU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SHU_AUTOMATION_ENABLED", "true")
    exports = tmp_path / "memory" / "exports"
    exports.mkdir(parents=True)
    source, target = exports / "note.txt", exports / "reviewed copy.txt"
    contents = "Synthetic file body"
    source.write_text(contents, encoding="utf-8")

    assert file_preview(str(source)) == 0
    output = capsys.readouterr().out
    assert contents not in output
    digest = json.loads(output)["sha256"]
    args = build_parser().parse_args([
        "files", "copy", str(source), str(target), "--sha256", digest, "--confirm",
    ])
    assert (args.command, args.file_action, args.sha256, args.confirm) == ("files", "copy", digest, True)

    def unexpected_input(_prompt):
        pytest.fail("An unconfirmed file copy must stop before asking for typed approval")

    monkeypatch.setattr("builtins.input", unexpected_input)
    assert file_copy(str(source), str(target), digest, confirmed=False) == 2
    assert not target.exists()
    assert "--confirm" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda _prompt: "NO")
    assert file_copy(str(source), str(target), digest, confirmed=True) == 2
    assert not target.exists()

    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")
    assert file_copy(str(source), str(target), digest, confirmed=True) == 0
    assert source.read_text(encoding="utf-8") == target.read_text(encoding="utf-8") == contents
    assert contents not in capsys.readouterr().out


def test_files_cli_rejects_a_source_changed_during_approval(monkeypatch, tmp_path, capsys):
    from app.cli import file_copy, file_preview

    monkeypatch.setenv("SHU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SHU_AUTOMATION_ENABLED", "true")
    exports = tmp_path / "memory" / "exports"
    exports.mkdir(parents=True)
    source, target = exports / "note.txt", exports / "destination.txt"
    source.write_text("First version", encoding="utf-8")
    assert file_preview(str(source)) == 0
    digest = json.loads(capsys.readouterr().out)["sha256"]

    def edit_then_approve(_prompt):
        source.write_text("New version", encoding="utf-8")
        return "YES"

    monkeypatch.setattr("builtins.input", edit_then_approve)
    assert file_copy(str(source), str(target), digest, confirmed=True) == 1
    assert not target.exists()
    assert "source changed since preview" in capsys.readouterr().out


def test_files_cli_moves_reviewed_bytes_and_can_reverse_the_move(monkeypatch, tmp_path, capsys):
    import sys

    from app.cli import file_move, file_preview

    if sys.platform != "win32":
        pytest.skip("Handle-based file moves require Windows")
    pytest.importorskip("win32file")
    monkeypatch.setenv("SHU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SHU_AUTOMATION_ENABLED", "true")
    exports = tmp_path / "memory" / "exports"
    folder = exports / "organized"
    folder.mkdir(parents=True)
    source, target = exports / "note.txt", folder / "reviewed note.txt"
    content = b"Synthetic file body for review"
    source.write_bytes(content)
    modification_time = source.stat().st_mtime_ns
    assert file_preview(str(source)) == 0
    digest = json.loads(capsys.readouterr().out)["sha256"]
    args = build_parser().parse_args(["files", "move", str(source), str(target), "--sha256", digest, "--confirm"])
    assert (args.command, args.file_action, args.sha256, args.confirm) == ("files", "move", digest, True)

    monkeypatch.setattr("builtins.input", lambda _prompt: "NO")
    assert file_move(str(source), str(target), digest, confirmed=True) == 2
    assert source.read_bytes() == content and not target.exists()

    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")
    assert file_move(str(source), str(target), digest, confirmed=True) == 0
    assert not source.exists() and target.read_bytes() == content
    assert target.stat().st_mtime_ns == modification_time
    assert file_move(str(target), str(source), digest, confirmed=True) == 0
    assert not target.exists() and source.read_bytes() == content
    output = capsys.readouterr().out
    assert "To undo" in output and content.decode() not in output


def test_restore_cli_reports_bad_backup_without_touching_live_db(monkeypatch, tmp_path, capsys):
    from app import cli
    from database.database import Database

    live = Database(tmp_path / "memory" / "shu.db")
    live.initialize()
    original = live.path.read_bytes()
    invalid = tmp_path / "not-sqlite.db"
    invalid.write_bytes(b"Invalid local backup")
    monkeypatch.setattr(cli, "_database", lambda: live)

    assert cli.db_restore(str(invalid), confirmed=True) == 1
    assert capsys.readouterr().out.strip() == "Restore was not applied: Restore source is not a valid versioned SHU backup"
    assert live.path.read_bytes() == original


def test_voice_chat_reports_missing_wake_word_model_without_traceback(
    monkeypatch, tmp_path, capsys
):
    missing_model = tmp_path / "missing-hey-shu.onnx"
    monkeypatch.setenv("SHU_WAKEWORD_MODEL_PATH", str(missing_model))
    monkeypatch.setenv("SHU_MICROPHONE_DEVICE", "")

    assert voice_chat(language=None, max_turns=1) == 1

    output = capsys.readouterr().out
    assert output.strip() == (
        "SHU voice setup error: FileNotFoundError. "
        "Check the configured microphone, speech model, or Hey SHU model path."
    )
    assert str(tmp_path) not in output


def test_email_authorization_failure_does_not_echo_provider_details(
    monkeypatch, capsys
):
    from app import cli

    class BrokenGmailOAuth:
        def __init__(self, _settings, _store):
            pass

        def authorize(self):
            raise RuntimeError("private-client-secret authorization-code")

    monkeypatch.setattr(cli, "get_settings", lambda: object())
    monkeypatch.setattr(cli, "WindowsCredentialStore", lambda: object())
    monkeypatch.setattr(cli, "GmailOAuth", BrokenGmailOAuth)

    assert email_auth("gmail", "login") == 1

    output = capsys.readouterr().out
    assert output.strip() == "Email authorization failed: RuntimeError"
    assert "private-client-secret" not in output
    assert "authorization-code" not in output


def test_email_auth_status_does_not_claim_cached_credentials_are_verified(
    monkeypatch, capsys
):
    from app import cli

    class CachedGmailOAuth:
        is_authorized = True

        def __init__(self, _settings, _store):
            pass

    monkeypatch.setattr(cli, "get_settings", lambda: object())
    monkeypatch.setattr(cli, "WindowsCredentialStore", lambda: object())
    monkeypatch.setattr(cli, "GmailOAuth", CachedGmailOAuth)

    assert email_auth("gmail", "status") == 0
    assert capsys.readouterr().out.strip() == (
        "Gmail OAuth: credential cache present (not live-verified)"
    )


def test_email_auth_live_verify_reports_success_without_account_data(
    monkeypatch, capsys
):
    from app import cli

    class VerifiedGmailOAuth:
        def __init__(self, _settings, _store):
            pass

        def verify_live(self):
            return None

    monkeypatch.setattr(cli, "get_settings", lambda: object())
    monkeypatch.setattr(cli, "WindowsCredentialStore", lambda: object())
    monkeypatch.setattr(cli, "GmailOAuth", VerifiedGmailOAuth)

    assert email_auth("gmail", "verify") == 0
    assert capsys.readouterr().out.strip() == (
        "Gmail OAuth: live verification succeeded; account data suppressed."
    )


def test_email_auth_live_verify_suppresses_provider_error_details(
    monkeypatch, capsys
):
    from app import cli

    class BrokenGmailOAuth:
        def __init__(self, _settings, _store):
            pass

        def verify_live(self):
            raise RuntimeError("private account response with token material")

    monkeypatch.setattr(cli, "get_settings", lambda: object())
    monkeypatch.setattr(cli, "WindowsCredentialStore", lambda: object())
    monkeypatch.setattr(cli, "GmailOAuth", BrokenGmailOAuth)

    assert email_auth("gmail", "verify") == 1
    output = capsys.readouterr().out.strip()
    assert output == "Email authorization live check failed: RuntimeError"
    assert "private account response" not in output
    assert "token material" not in output


def test_email_auth_parser_exposes_explicit_live_verification():
    args = build_parser().parse_args(
        ["auth", "email", "verify", "--provider", "gmail"]
    )

    assert args.command == "auth"
    assert args.email_auth_action == "verify"
    assert args.provider == "gmail"


def test_mic_check_parser_accepts_an_explicit_device_and_bounded_duration_option():
    args = build_parser().parse_args(
        ["mic-check", "--device", "4", "--seconds", "2.5"]
    )

    assert args.command == "mic-check"
    assert args.device == 4
    assert args.seconds == 2.5


def test_mic_check_cancellation_never_starts_capture(monkeypatch, capsys):
    from app import cli

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(microphone_device=1, sample_rate=16_000),
    )
    monkeypatch.setattr(
        "sounddevice.query_devices",
        lambda: [{"name": "Test input", "max_input_channels": 1}],
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    called = []

    def unexpected_capture(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("Capture must not start after cancellation")

    monkeypatch.setattr(cli, "capture_input_level", unexpected_capture)

    result = mic_check(0, 1.0)

    assert result == 2
    assert called == []
    assert "no audio was recorded" in capsys.readouterr().out


def test_email_reply_and_forward_have_explicit_send_options():
    parser = build_parser()
    reply = parser.parse_args(["email", "reply", "source-id"])
    forward = parser.parse_args(
        ["email", "forward", "source-id", "--to", "team@example.com", "--send"]
    )

    assert (reply.email_action, reply.message_id, reply.send) == ("reply", "source-id", False)
    assert (forward.email_action, forward.message_id, forward.to, forward.send) == (
        "forward", "source-id", "team@example.com", True
    )


def test_contacts_parser_supports_confirmation_for_deletion():
    args = build_parser().parse_args(
        ["contacts", "delete", "contact-id", "--confirm-delete"]
    )

    assert (args.contacts_action, args.contact_id, args.confirm_delete) == (
        "delete", "contact-id", True
    )


def test_task_queue_parser_exposes_persistent_queue_controls():
    parser = build_parser()
    queue = parser.parse_args(["tasks", "queue", "--limit", "7"])
    run_next = parser.parse_args(["tasks", "run-next", "--confirm"])

    assert (queue.task_action, queue.limit) == ("queue", 7)
    assert (run_next.task_action, run_next.confirm) == ("run-next", True)


def test_task_queue_command_lists_planned_tasks_without_running_them(
    monkeypatch, capsys
):
    from app import cli

    queued = [
        {
            "task_id": "task-1",
            "request": "Read a public status",
            "status": "planned",
            "started_at": "2026-11-24T12:00:00+00:00",
        }
    ]

    class FakePlanner:
        def list_queued(self, *, limit):
            assert limit == 5
            return queued

    class NeverExecute:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("Listing the queue must never execute tasks")

    monkeypatch.setattr(cli, "_task_services", lambda: (FakePlanner(), NeverExecute()))

    assert cli.task_queue(5) == 0
    assert json.loads(capsys.readouterr().out) == {"count": 1, "tasks": queued}


def test_run_next_requires_plan_confirmation_and_per_tool_approval(
    monkeypatch, tmp_path, capsys
):
    from app import cli
    from app.security.policy import RiskLevel
    from app.security.registry import ToolRegistry, ToolSpec
    from app.tasks.executor import TaskExecutor
    from app.tasks.planner import TaskPlanner

    database = Database(tmp_path / "task-queue.db")
    database.initialize()
    registry = ToolRegistry(database)
    calls = []
    registry.register(
        ToolSpec(
            name="modify_test_value",
            description="Modify a test value",
            risk=RiskLevel.MODIFICATION,
            handler=lambda: calls.append("executed") or "done",
            validator=lambda _arguments: {},
            verifier=lambda value, _arguments: value == "done",
        )
    )
    planner = TaskPlanner(database, registry)
    task_id = planner.create(
        "Update a test value",
        [{"tool": "modify_test_value", "arguments": {}}],
    )
    executor = TaskExecutor(database, planner, registry)
    monkeypatch.setattr(cli, "_task_services", lambda: (planner, executor))

    assert cli.task_run_next(confirmed=False) == 2
    assert calls == []
    assert planner.preview(task_id)["status"] == "planned"

    answers = iter(["YES", "no"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert cli.task_run_next(confirmed=True) == 1
    assert calls == []
    assert planner.preview(task_id)["status"] == "partially_completed"
    output = capsys.readouterr().out
    assert "Next queued task" in output
    assert "Tool approval required: modify_test_value" in output


def test_run_next_refuses_a_plan_changed_after_preview(monkeypatch, tmp_path, capsys):
    from app import cli
    from app.security.policy import RiskLevel
    from app.security.registry import ToolRegistry, ToolSpec
    from app.tasks.executor import TaskExecutor
    from app.tasks.planner import TaskPlanner

    database = Database(tmp_path / "changed-queue-task.db")
    database.initialize()
    registry = ToolRegistry(database)
    calls = []
    registry.register(
        ToolSpec(
            name="modify_test_value",
            description="Modify a test value",
            risk=RiskLevel.MODIFICATION,
            handler=lambda: calls.append("modified") or "done",
            validator=lambda _arguments: {},
            verifier=lambda value, _arguments: value == "done",
        )
    )
    registry.register(
        ToolSpec(
            name="read_test_value",
            description="Read a test value",
            risk=RiskLevel.READ_ONLY,
            handler=lambda: calls.append("read") or "value",
            validator=lambda _arguments: {},
        )
    )
    planner = TaskPlanner(database, registry)
    task_id = planner.create(
        "Modify a value",
        [{"tool": "modify_test_value", "arguments": {}}],
    )
    executor = TaskExecutor(database, planner, registry)
    monkeypatch.setattr(cli, "_task_services", lambda: (planner, executor))

    def change_saved_plan(_prompt):
        replacement = planner.validate_steps(
            [{"tool": "read_test_value", "arguments": {}}]
        )
        with database.connect() as connection:
            with connection:
                connection.execute(
                    "UPDATE tasks SET plan_json=? WHERE task_id=?",
                    (json.dumps(replacement), task_id),
                )
        return "YES"

    monkeypatch.setattr("builtins.input", change_saved_plan)

    assert cli.task_run_next(confirmed=True) == 1
    assert calls == []
    assert planner.preview(task_id)["status"] == "planned"
    assert "could not run: ValueError" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["checkpoint", "plan", "request"])
def test_task_resume_requires_a_new_review_when_the_saved_task_changes(
    monkeypatch, tmp_path, capsys, change
):
    from app import cli
    from app.security.policy import RiskLevel
    from app.security.registry import ToolRegistry, ToolSpec
    from app.tasks.executor import TaskExecutor
    from app.tasks.planner import TaskPlanner

    database = Database(tmp_path / "cli-resume.db")
    database.initialize()
    registry = ToolRegistry(database)
    calls = []

    def read_value(key):
        calls.append(key)
        if key == "first" or (key == "second" and change == "checkpoint"):
            registry.emergency_stop.trigger()
        return key

    registry.register(
        ToolSpec(
            name="read_value",
            description="Read a test value",
            risk=RiskLevel.READ_ONLY,
            handler=read_value,
            validator=lambda args: {"key": args["key"]},
        )
    )
    planner = TaskPlanner(database, registry)
    steps = [
        {"tool": "read_value", "arguments": {"key": key}}
        for key in ("first", "second", "third")
    ]
    task_id = planner.create("Read three values", steps)
    executor = TaskExecutor(database, planner, registry)
    assert executor.execute(task_id)["status"] == "partially_completed"
    registry.emergency_stop.reset()
    monkeypatch.setattr(cli, "_task_services", lambda: (planner, executor))

    def approve_after_change(_prompt):
        assert '"key": "second"' in capsys.readouterr().out
        if change == "checkpoint":
            competing_executor = TaskExecutor(database, planner, registry)
            assert competing_executor.resume(task_id)["status"] == "partially_completed"
            registry.emergency_stop.reset()
        else:
            with database.connect() as connection:
                with connection:
                    if change == "plan":
                        steps[1] = {"tool": "read_value", "arguments": {"key": "replacement"}}
                        connection.execute(
                            "UPDATE tasks SET plan_json=? WHERE task_id=?",
                            (json.dumps(planner.validate_steps(steps)), task_id),
                        )
                    else:
                        connection.execute(
                            "UPDATE tasks SET request=? WHERE task_id=?",
                            ("Read a revised request", task_id),
                        )
        return "YES"

    monkeypatch.setattr("builtins.input", approve_after_change)
    assert cli.task_resume(task_id, confirmed=True) == 1
    assert "Review the current task status and remaining steps" in capsys.readouterr().out
    assert calls == (["first", "second"] if change == "checkpoint" else ["first"])
    assert planner.preview(task_id)["status"] == "partially_completed"

    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")
    assert cli.task_resume(task_id, confirmed=True) == 0
    expected_second = "replacement" if change == "plan" else "second"
    assert calls == ["first", expected_second, "third"]


@pytest.mark.parametrize(
    ("action", "final_status"),
    [("retry", "cancelled"), ("accept-complete", "completed_manual_review")],
)
def test_task_recover_refuses_to_apply_an_old_confirmation_to_a_new_uncertain_step(
    monkeypatch, tmp_path, capsys, action, final_status
):
    from app import cli
    from app.security.policy import RiskLevel
    from app.security.registry import ToolRegistry, ToolSpec
    from app.tasks.executor import TaskExecutor
    from app.tasks.planner import TaskPlanner

    database = Database(tmp_path / "cli-interrupted.db")
    database.initialize()
    registry = ToolRegistry(database)
    calls = []
    registry.register(
        ToolSpec(
            name="read_value",
            description="Read a test value",
            risk=RiskLevel.READ_ONLY,
            handler=lambda key: calls.append(key),
            validator=lambda args: {"key": args["key"]},
        )
    )
    planner = TaskPlanner(database, registry)
    task_id = planner.create(
        "Review the uncertain value",
        [
            {"tool": "read_value", "arguments": {"key": "first"}},
            {"tool": "read_value", "arguments": {"key": "second"}},
        ],
    )
    executor = TaskExecutor(database, planner, registry)
    monkeypatch.setattr(cli, "_task_services", lambda: (planner, executor))
    with database.connect() as connection:
        with connection:
            connection.execute(
                "UPDATE tasks SET status='interrupted',inflight_step=1 WHERE task_id=?",
                (task_id,),
            )

    def approve_after_step_changes(_prompt):
        assert "Uncertain step 1:" in capsys.readouterr().out
        with database.connect() as connection:
            with connection:
                connection.execute(
                    "UPDATE tasks SET inflight_step=2,checkpoint_json=? WHERE task_id=?",
                    (json.dumps([{"step": 1, "status": "verified", "tool": "read_value"}]), task_id),
                )
        return "YES"

    monkeypatch.setattr("builtins.input", approve_after_step_changes)
    assert cli.task_recover(task_id, action, confirmed=True) == 1
    assert "Interrupted task changed after review" in capsys.readouterr().out
    assert executor.preview_interrupted(task_id)["uncertain_step_number"] == 2
    assert calls == []

    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")
    assert cli.task_recover(task_id, action, confirmed=True) == 0
    assert planner.preview(task_id)["status"] == final_status
    assert calls == []


def test_whatsapp_contact_resolution_requires_explicit_duplicate_choice(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    contacts = ContactBook(database)
    contacts.add("Sam Lee", "+14155550123", confirmed=True)
    contacts.add("Sam Lee", "+442079460123", confirmed=True)

    result = resolve_whatsapp_recipient(
        "sam lee", contacts, input_fn=lambda _prompt: "2"
    )

    assert result is not None
    assert result.phone_e164 == "+442079460123"


def test_whatsapp_contact_resolution_does_not_guess_unknown_names(tmp_path, capsys):
    database = Database(tmp_path / "shu.db")
    database.initialize()

    result = resolve_whatsapp_recipient("Sam", ContactBook(database))

    assert result is None
    assert "not resolved" in capsys.readouterr().out


def test_whatsapp_draft_resolves_exact_contact_before_creating_draft(
    monkeypatch, tmp_path, capsys
):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    ContactBook(database).add("Maya Das", "+919876543210", confirmed=True)

    class FakeService:
        def __init__(self):
            self.database = database
            self.created = None

        def create_draft(self, channel, recipient, body, **kwargs):
            self.created = (channel, recipient, body, kwargs)
            return "draft-id"

    service = FakeService()
    monkeypatch.setattr("app.cli._communication_service", lambda: service)
    answers = iter(["maya das", "Hello from SHU", "."])
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))

    assert communication_draft("whatsapp") == 0
    assert service.created == (
        "whatsapp",
        "+919876543210",
        "Hello from SHU",
        {"subject": "", "attachments": []},
    )
    assert "Resolved contact: Maya Das (+919876543210)" in capsys.readouterr().out


def test_contacts_add_only_writes_after_typed_confirmation(monkeypatch, tmp_path):
    database = Database(tmp_path / "shu.db")
    monkeypatch.setattr("app.cli._database", lambda: database)
    answers = iter(["Maya Das", "+919876543210", "YES"])
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))

    assert contacts_add() == 0
    assert ContactBook(database).resolve("Maya Das").phone_e164 == "+919876543210"


@pytest.mark.parametrize(
    ("send", "confirmation", "exit_code"),
    [(False, "YES", 0), (False, "SEND", 2), (True, "SEND", 0), (True, "YES", 2)],
)
def test_email_reply_cli_confirms_the_reviewed_delivery_mode(
    monkeypatch, capsys, send, confirmation, exit_code
):
    calls = []
    prepare_modes = []

    class FakeProvider:
        def read_message(self, message_id):
            assert message_id == "source-id"
            return {
                "from": "person@example.com",
                "subject": "Hello",
                "body": "Untrusted source text",
            }

    class FakeCommunications:
        database = object()
        providers = {"email": FakeProvider()}

    class FakeActionService:
        def __init__(self, database, provider):
            assert database is FakeCommunications.database
            assert isinstance(provider, FakeProvider)

        def prepare(self, action, message_id, comment, *, recipient=None, send=False):
            prepare_modes.append(send)
            return SimpleNamespace(
                action=action,
                source_message_id=message_id,
                source={"from": "person@example.com", "subject": "Hello", "body": "Source"},
                source_attachments=(),
                recipient="person@example.com",
                subject="Hello",
                comment=comment,
                send=send,
                digest="exact-digest",
            )

        def execute(self, preview, *, confirmed, expected_digest, send=False):
            calls.append((preview.comment, confirmed, expected_digest, send))
            return "provider-draft-id"

    answers = iter(["Reviewed reply", ".", confirmation])
    monkeypatch.setattr("app.cli._communication_service", lambda: FakeCommunications())
    monkeypatch.setattr("app.cli.EmailActionService", FakeActionService)
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))

    assert email_related_action("reply", "source-id", send=send) == exit_code
    assert prepare_modes == [send]
    assert calls == ([("Reviewed reply", True, "exact-digest", send)] if exit_code == 0 else [])
    output = capsys.readouterr().out
    assert "Untrusted source text" in output
    assert "Approval digest: exact-digest" in output
    assert ("Delivery: Send now" if send else "Delivery: Save as unsent provider draft") in output
    if exit_code == 0:
        success_message = "Email accepted by provider" if send else "Unsent provider draft created"
        assert success_message in output
    else:
        assert "Email action cancelled." in output


def test_communication_send_warns_of_unknown_outcome_without_provider_details(monkeypatch, capsys):
    def send(draft_id, *, confirmed, expected_digest):
        assert (draft_id, confirmed, expected_digest) == ("test-draft", True, "reviewed-digest")
        raise DeliveryOutcomeUnknown("synthetic private provider detail")

    monkeypatch.setattr("app.cli._communication_service", lambda: SimpleNamespace(send=send))
    assert communication_send("test-draft", "reviewed-digest", confirmed=True) == 1
    output = capsys.readouterr().out
    assert "Delivery status is unknown. Check the provider before sending another copy." in output
    assert "synthetic private provider detail" not in output


def test_provider_draft_cli_requires_matching_preview_and_typed_yes(monkeypatch):
    class FakeService:
        def __init__(self):
            self.save_call = None

        def preview(self, draft_id):
            assert draft_id == "draft-id"
            return SimpleNamespace(
                channel="email",
                recipient="person@example.com",
                subject="Hello",
                body="Reviewed body",
                attachments=(),
                digest="review-digest",
            )

        def save_provider_draft(self, draft_id, *, confirmed, expected_digest):
            self.save_call = (draft_id, confirmed, expected_digest)
            return "provider-draft-id"

    service = FakeService()
    monkeypatch.setattr("app.cli._communication_service", lambda: service)
    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")

    result = communication_save_provider_draft(
        "draft-id", "review-digest", confirmed=True
    )

    assert result == 0
    assert service.save_call == ("draft-id", True, "review-digest")
