import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from email import message_from_bytes
from threading import Event
from unittest.mock import Mock

import pytest

from app.applications.communications import (
    DeliveryOutcomeUnknown,
    GmailApiProvider,
    MicrosoftGraphEmailProvider,
    ProviderNotConfigured,
)
from app.applications.email_actions import EmailActionService
from database.database import Database


class ActionProvider:
    requires_forwarded_attachment_data = True

    def __init__(self):
        self.source = {
            "id": "message-1",
            "thread_id": "thread-1",
            "internet_message_id": "<source@example.com>",
            "references": "<older@example.com>",
            "from": "Sender <sender@example.com>",
            "reply_to": "reply@example.com",
            "to": "shu@example.com",
            "subject": "Project update",
            "date": "Mon, 01 Jan 2026 10:00:00 +0000",
            "body": "Original email body",
            "has_attachments": True,
        }
        self.attachments = [
            {"id": "file-1", "filename": "brief.txt", "size": 4}
        ]
        self.calls = []
        self.downloads = 0

    def read_message(self, message_id):
        assert message_id == self.source["id"]
        return dict(self.source)

    def list_attachments(self, message_id):
        return list(self.attachments)

    def download_attachment(self, message_id, attachment_id):
        assert (message_id, attachment_id) == ("message-1", "file-1")
        self.downloads += 1
        return b"data"

    def create_reply_draft(self, *args):
        self.calls.append(("reply_draft", args))
        return "provider-draft-id"

    def send_reply(self, *args):
        self.calls.append(("reply_send", args))
        return "provider-message-id"

    def create_forward_draft(self, *args, **kwargs):
        self.calls.append(("forward_draft", args, kwargs))
        return "provider-draft-id"

    def send_forward(self, *args, **kwargs):
        self.calls.append(("forward_send", args, kwargs))
        return "provider-message-id"


@pytest.fixture
def database(tmp_path):
    result = Database(tmp_path / "shu.db")
    result.initialize()
    return result


def test_reply_uses_reply_to_and_confirmation_bound_to_source(database):
    provider = ActionProvider()
    service = EmailActionService(database, provider)
    preview = service.prepare("reply", "message-1", "Thanks for the update.")

    assert preview.recipient == "reply@example.com"
    assert preview.subject == "Project update"
    with pytest.raises(PermissionError, match="explicit confirmation"):
        service.execute(
            preview,
            confirmed=False,
            expected_digest=preview.digest,
        )
    assert provider.calls == []

    provider.source["body"] = "Changed since preview"
    with pytest.raises(PermissionError, match="source email changed"):
        service.execute(
            preview,
            confirmed=True,
            expected_digest=preview.digest,
        )
    assert provider.calls == []


def test_forward_preview_binds_attachment_hash_and_audits_provider_draft(database):
    provider = ActionProvider()
    service = EmailActionService(database, provider)
    preview = service.prepare(
        "forward", "message-1", "Please review.", recipient="team@example.com"
    )

    assert preview.subject == "Fwd: Project update"
    assert preview.source_attachments[0]["filename"] == "brief.txt"
    assert preview.attachment_data == (("brief.txt", b"data"),)
    assert provider.downloads == 1
    assert service.execute(
        preview,
        confirmed=True,
        expected_digest=preview.digest,
    ) == "provider-draft-id"
    assert provider.downloads == 2
    assert provider.calls[0][0] == "forward_draft"
    assert provider.calls[0][2]["attachments"] == [("brief.txt", b"data")]
    with database.connect() as connection:
        audit = connection.execute(
            "SELECT tool,result,approval FROM audit_logs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    assert tuple(audit) == ("email_forward", "provider_draft_created", "approved")


def test_explicit_send_mode_records_success_without_auto_sending(database):
    provider = ActionProvider()
    service = EmailActionService(database, provider)
    preview = service.prepare("reply", "message-1", "Reviewed reply", send=True)

    assert provider.calls == []
    assert service.execute(
        preview,
        confirmed=True,
        expected_digest=preview.digest,
        send=True,
    ) == "provider-message-id"
    assert provider.calls[0][0] == "reply_send"
    with database.connect() as connection:
        audit = connection.execute(
            "SELECT result,action_summary FROM audit_logs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    assert audit[0] == "sent"
    assert "mode=send" in audit[1]
    assert provider.source["reply_to"] not in audit[1]
    assert "provider-message-id" not in audit[1]

    restarted = EmailActionService(Database(database.path), provider)
    reviewed_again = restarted.prepare("reply", "message-1", "Reviewed reply", send=True)
    with pytest.raises(ValueError, match="already completed"):
        restarted.execute(
            reviewed_again, confirmed=True, expected_digest=reviewed_again.digest, send=True
        )
    assert len(provider.calls) == 1

    draft = restarted.prepare("reply", "message-1", "Reviewed reply")
    assert restarted.execute(draft, confirmed=True, expected_digest=draft.digest) == "provider-draft-id"


@pytest.mark.parametrize("action", ["reply", "forward"])
@pytest.mark.parametrize("preview_send", [False, True])
def test_email_action_rejects_a_different_delivery_mode(database, action, preview_send):
    provider = ActionProvider()
    service = EmailActionService(database, provider)
    recipient = "team@example.com" if action == "forward" else None
    preview = service.prepare(
        action, "message-1", "Reviewed comment", recipient=recipient, send=preview_send
    )
    other_mode = replace(preview, send=not preview_send)
    assert other_mode.digest != preview.digest

    with pytest.raises(PermissionError, match="delivery mode changed"):
        service.execute(
            preview, confirmed=True, expected_digest=preview.digest, send=not preview_send
        )
    with pytest.raises(PermissionError, match="preview changed"):
        service.execute(
            other_mode, confirmed=True, expected_digest=preview.digest, send=not preview_send
        )
    assert provider.calls == []


@pytest.mark.parametrize(
    "changes", [{"recipient": "other@example.com"}, {"subject": "A different subject"}]
)
def test_email_action_digest_rejects_altered_reply_fields(database, changes):
    provider = ActionProvider()
    service = EmailActionService(database, provider)
    preview = service.prepare("reply", "message-1", "Reviewed reply")

    with pytest.raises(PermissionError, match="preview changed"):
        service.execute(
            replace(preview, **changes), confirmed=True, expected_digest=preview.digest
        )
    assert provider.calls == []


@pytest.mark.parametrize(
    ("provider_error", "provider_result", "audit_result"),
    [
        (TimeoutError("provider-private-details"), None, "unknown_after_timeout"),
        (RuntimeError("provider-private-details"), None, "unknown"),
        (None, " \n", "unknown"),
    ],
)
def test_uncertain_email_action_cannot_be_replayed_after_restart(
    database, provider_error, provider_result, audit_result
):
    provider = ActionProvider()
    provider.create_reply_draft = Mock(side_effect=provider_error, return_value=provider_result)
    service = EmailActionService(database, provider)
    preview = service.prepare("reply", "message-1", "Reviewed reply")

    with pytest.raises(DeliveryOutcomeUnknown, match="inspect the provider before retrying") as error:
        service.execute(
            preview,
            confirmed=True,
            expected_digest=preview.digest,
        )
    assert "provider-private-details" not in str(error.value)
    assert error.value.__suppress_context__

    restarted = EmailActionService(Database(database.path), provider)
    reviewed_again = restarted.prepare("reply", "message-1", "Reviewed reply")
    with pytest.raises(DeliveryOutcomeUnknown, match="already attempted"):
        restarted.execute(reviewed_again, confirmed=True, expected_digest=reviewed_again.digest)
    provider.create_reply_draft.assert_called_once()
    with database.connect() as connection:
        result = connection.execute("SELECT result FROM audit_logs").fetchone()
    assert result["result"] == audit_result


def test_email_action_claim_blocks_concurrent_execution_and_survives_interruption(database):
    provider = ActionProvider()
    provider_started = Event()
    release_provider = Event()

    def interrupted_provider(*args):
        provider_started.set()
        assert release_provider.wait(5)
        raise SystemExit

    provider.send_reply = Mock(side_effect=interrupted_provider)
    first = EmailActionService(database, provider)
    second = EmailActionService(Database(database.path), provider)
    preview = first.prepare("reply", "message-1", "Reviewed reply", send=True)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            first.execute, preview, confirmed=True, expected_digest=preview.digest, send=True
        )
        try:
            assert provider_started.wait(5)
            with pytest.raises(DeliveryOutcomeUnknown, match="already attempted"):
                second.execute(preview, confirmed=True, expected_digest=preview.digest, send=True)
        finally:
            release_provider.set()
        with pytest.raises(SystemExit):
            pending.result(timeout=5)

    restarted = EmailActionService(Database(database.path), provider)
    with pytest.raises(DeliveryOutcomeUnknown, match="already attempted"):
        restarted.execute(preview, confirmed=True, expected_digest=preview.digest, send=True)
    provider.send_reply.assert_called_once()


def test_email_preflight_configuration_failure_allows_reviewed_retry(database):
    provider = ActionProvider()
    provider.send_reply = Mock(
        side_effect=[ProviderNotConfigured("provider-private-details"), "provider-message-id"]
    )
    service = EmailActionService(database, provider)
    preview = service.prepare("reply", "message-1", "Reviewed reply", send=True)
    with pytest.raises(ProviderNotConfigured, match="provider is unavailable") as error:
        service.execute(preview, confirmed=True, expected_digest=preview.digest, send=True)
    assert "provider-private-details" not in str(error.value)

    restarted = EmailActionService(Database(database.path), provider)
    assert restarted.execute(
        preview, confirmed=True, expected_digest=preview.digest, send=True
    ) == "provider-message-id"


def test_provider_acceptance_with_failed_audit_update_blocks_replay(database):
    provider = ActionProvider()
    service = EmailActionService(database, provider)
    preview = service.prepare("reply", "message-1", "Reviewed reply", send=True)
    with database.connect() as connection, connection:
        connection.execute(
            """CREATE TRIGGER fail_audit_update BEFORE UPDATE ON audit_logs BEGIN
                   SELECT RAISE(ABORT, 'synthetic database failure');
               END"""
        )

    with pytest.raises(DeliveryOutcomeUnknown, match="could not be recorded"):
        service.execute(preview, confirmed=True, expected_digest=preview.digest, send=True)
    restarted = EmailActionService(Database(database.path), provider)
    with pytest.raises(DeliveryOutcomeUnknown, match="already attempted"):
        restarted.execute(preview, confirmed=True, expected_digest=preview.digest, send=True)
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("outcome", "prior_error"),
    [
        ("sent", ValueError),
        ("unknown_after_timeout", DeliveryOutcomeUnknown),
        ("failed:HTTPStatusError", DeliveryOutcomeUnknown),
        (None, DeliveryOutcomeUnknown),
        ("provider_not_configured", None),
    ],
)
def test_email_action_respects_legacy_audit_history(database, outcome, prior_error):
    provider = ActionProvider()
    service = EmailActionService(database, provider)
    preview = service.prepare("reply", "message-1", "Reviewed reply", send=True)
    old_summary = (
        f"action=reply; source=message-1; recipient=reply@example.com; digest={preview.digest}; mode=send"
    )
    old_rows = [("legacy-start", old_summary, "provider_action_started")]
    if outcome == "sent":
        old_rows.append(("legacy-finish", old_summary + "; external_id=provider-id", outcome))
    elif outcome is not None:
        old_rows.append(("legacy-finish", old_summary, outcome))
    # A newer complete preflight failure must not hide an earlier provider attempt.
    old_rows += [
        ("legacy-preflight-start", old_summary, "provider_action_started"),
        ("legacy-preflight-finish", old_summary, "provider_not_configured"),
    ]
    with database.connect() as connection, connection:
        connection.executemany(
            """INSERT INTO audit_logs(log_id,actor,tool,action_summary,risk,approval,result,timestamp)
               VALUES(?,'email_action_service','email_reply',?,'L3','approved',?,'2026-11-26T00:00:00Z')""",
            old_rows,
        )

    if prior_error is None:
        assert service.execute(
            preview, confirmed=True, expected_digest=preview.digest, send=True
        ) == "provider-message-id"
    else:
        with pytest.raises(prior_error, match="already"):
            service.execute(preview, confirmed=True, expected_digest=preview.digest, send=True)
        assert provider.calls == []


def test_gmail_reply_draft_uses_thread_headers_and_does_not_send(monkeypatch):
    response = Mock()
    response.json.return_value = {"id": "gmail-reply-draft"}
    post = Mock(return_value=response)
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    provider = GmailApiProvider(lambda: "gmail-token")
    provider.read_message = lambda _message_id: {
        "thread_id": "thread-42",
        "internet_message_id": "<original@example.com>",
        "references": "<older@example.com>",
    }

    result = provider.create_reply_draft(
        "source-id", "reply@example.com", "Subject", "Reply text"
    )

    assert result == "gmail-reply-draft"
    args, kwargs = post.call_args
    assert args[0] == "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
    message_json = kwargs["json"]["message"]
    assert message_json["threadId"] == "thread-42"
    mime = message_from_bytes(
        base64.urlsafe_b64decode(message_json["raw"] + "=" * (-len(message_json["raw"]) % 4))
    )
    assert mime["To"] == "reply@example.com"
    assert mime["Subject"] == "Subject"
    assert mime["In-Reply-To"] == "<original@example.com>"
    assert mime["References"] == "<older@example.com> <original@example.com>"
    assert mime.get_payload(decode=True).decode().strip() == "Reply text"


def test_gmail_forward_draft_quotes_source_and_carries_reviewed_attachment(monkeypatch):
    response = Mock()
    response.json.return_value = {"id": "gmail-forward-draft"}
    post = Mock(return_value=response)
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    provider = GmailApiProvider(lambda: "gmail-token")

    result = provider.create_forward_draft(
        "source-id",
        "team@example.com",
        "Fwd: Subject",
        "Please review",
        source={
            "from": "sender@example.com",
            "date": "Mon, 01 Jan 2026 10:00:00 +0000",
            "subject": "Subject",
            "body": "Original body",
        },
        attachments=[("brief.txt", b"data")],
    )

    assert result == "gmail-forward-draft"
    raw = post.call_args.kwargs["json"]["message"]["raw"]
    mime = message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert mime["To"] == "team@example.com"
    assert mime["Subject"] == "Fwd: Subject"
    parts = mime.get_payload()
    assert "Original body" in parts[0].get_payload(decode=True).decode()
    assert parts[1].get_filename() == "brief.txt"
    assert parts[1].get_payload(decode=True) == b"data"


def test_graph_forward_draft_uses_native_route(monkeypatch):
    response = Mock()
    response.json.return_value = {"id": "graph-related-draft"}
    post = Mock(return_value=response)
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    provider = MicrosoftGraphEmailProvider(lambda: "graph-token")

    result = provider.create_forward_draft(
        "message/id", "team@example.com", "Fwd: Subject", "Forward comment"
    )

    assert result == "graph-related-draft"
    args, kwargs = post.call_args
    assert args[0] == "https://graph.microsoft.com/v1.0/me/messages/message%2Fid/createForward"
    assert kwargs["json"] == {
        "message": {"toRecipients": [{"emailAddress": {"address": "team@example.com"}}]},
        "comment": "Forward comment",
    }
    assert kwargs["headers"]["Authorization"] == "Bearer graph-token"


def test_graph_forward_send_uses_native_route(monkeypatch):
    response = Mock()
    response.headers = {"request-id": "graph-request-id"}
    post = Mock(return_value=response)
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    provider = MicrosoftGraphEmailProvider(lambda: "graph-token")

    result = provider.send_forward("message-id", "to@example.com", "Subject", "Reviewed body")

    assert result == "graph-request-id"
    args, kwargs = post.call_args
    assert args[0] == "https://graph.microsoft.com/v1.0/me/messages/message-id/forward"
    assert kwargs["json"] == {
        "message": {"toRecipients": [{"emailAddress": {"address": "to@example.com"}}]},
        "comment": "Reviewed body",
    }


def _graph_reply_draft(*addresses):
    return {
        "id": "reply/draft",
        "isDraft": True,
        "toRecipients": [{"emailAddress": {"address": address}} for address in addresses],
        "ccRecipients": [],
        "bccRecipients": [],
    }


@pytest.mark.parametrize("send", [False, True])
def test_graph_reply_binds_reviewed_recipient_when_source_has_several(database, monkeypatch, send):
    provider = MicrosoftGraphEmailProvider(lambda: "graph-token")
    provider.read_message = Mock(return_value={
        "id": "message/id",
        "from": "sender@example.com",
        "reply_to": ["reply@example.com", "second@example.com"],
        "subject": "Reviewed subject",
    })
    service = EmailActionService(database, provider)
    preview = service.prepare("reply", "message/id", "Reviewed body", send=send)
    assert preview.recipient == "reply@example.com"

    create = Mock()
    create.json.return_value = _graph_reply_draft("reply@example.com", "second@example.com")
    update = Mock()
    update.json.return_value = _graph_reply_draft("reply@example.com")
    accepted = Mock()
    accepted.headers = {"request-id": "graph-request-id"}
    patch = Mock(return_value=update)

    def post_request(path, **_kwargs):
        if path.endswith("/send"):
            patch.assert_called_once()
            update.json.assert_called_once()
            return accepted
        return create

    post = Mock(side_effect=post_request)
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    monkeypatch.setattr("app.applications.communications.httpx.patch", patch)

    result = service.execute(preview, confirmed=True, expected_digest=preview.digest, send=send)

    expected_envelope = {
        "toRecipients": [{"emailAddress": {"address": preview.recipient}}],
        "ccRecipients": [],
        "bccRecipients": [],
    }
    create_call = post.call_args_list[0]
    assert create_call.args == ("https://graph.microsoft.com/v1.0/me/messages/message%2Fid/createReply",)
    assert create_call.kwargs["json"] == {"comment": "Reviewed body", "message": expected_envelope}
    assert create_call.kwargs["headers"] == {"Authorization": "Bearer graph-token"}
    patch.assert_called_once_with(
        "https://graph.microsoft.com/v1.0/me/messages/reply%2Fdraft",
        headers={"Authorization": "Bearer graph-token"},
        json=expected_envelope,
        timeout=20,
    )
    if send:
        assert result == "graph-request-id"
        assert post.call_count == 2
        assert post.call_args.args == ("https://graph.microsoft.com/v1.0/me/messages/reply%2Fdraft/send",)
        assert "json" not in post.call_args.kwargs
    else:
        assert result == "reply/draft"
        assert post.call_count == 1


def test_graph_reply_draft_with_exact_envelope_requires_no_update(monkeypatch):
    create = Mock()
    create.json.return_value = _graph_reply_draft("reply@example.com")
    post = Mock(return_value=create)
    patch = Mock()
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    monkeypatch.setattr("app.applications.communications.httpx.patch", patch)
    provider = MicrosoftGraphEmailProvider(lambda: "graph-token")

    assert provider.create_reply_draft(
        "message-id", "reply@example.com", "Subject", "Reply body"
    ) == "reply/draft"
    post.assert_called_once()
    patch.assert_not_called()


@pytest.mark.parametrize(
    "changed_fields",
    [
        {"toRecipients": [{"emailAddress": {"address": "other@example.com"}}]},
        {"ccRecipients": [{"emailAddress": {"address": "extra@example.com"}}]},
        {"bccRecipients": [{"emailAddress": {"address": "hidden@example.com"}}]},
        {"bccRecipients": None},
        {"isDraft": False},
        {"id": "different-draft"},
    ],
)
def test_graph_reply_never_sends_an_unverified_draft(monkeypatch, changed_fields):
    create = Mock()
    create.json.return_value = _graph_reply_draft("wrong@example.com")
    update = Mock()
    update.json.return_value = {**_graph_reply_draft("reply@example.com"), **changed_fields}
    post = Mock(return_value=create)
    patch = Mock(return_value=update)
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    monkeypatch.setattr("app.applications.communications.httpx.patch", patch)
    provider = MicrosoftGraphEmailProvider(lambda: "graph-token")

    with pytest.raises(RuntimeError, match="did not confirm the reviewed reply recipient"):
        provider.send_reply("message-id", "reply@example.com", "Subject", "Reply body")
    post.assert_called_once()
    assert post.call_args.args[0].endswith("/createReply")
    patch.assert_called_once()


def test_gmail_direct_reply_send_uses_source_thread_and_rfc_headers(monkeypatch):
    response = Mock()
    response.json.return_value = {"id": "gmail-reply-id"}
    post = Mock(return_value=response)
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    provider = GmailApiProvider(lambda: "gmail-token")
    provider.read_message = lambda _message_id: {
        "thread_id": "thread-42",
        "internet_message_id": "<original@example.com>",
        "references": "",
    }

    assert provider.send_reply(
        "source-id", "reply@example.com", "Subject", "Reviewed body"
    ) == "gmail-reply-id"
    args, kwargs = post.call_args
    assert args[0] == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    assert kwargs["json"]["threadId"] == "thread-42"
    raw = kwargs["json"]["raw"]
    mime = message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert mime["In-Reply-To"] == "<original@example.com>"
    assert mime["References"] == "<original@example.com>"
