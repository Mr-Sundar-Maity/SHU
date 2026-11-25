import base64
from dataclasses import replace
from email import message_from_bytes
from unittest.mock import Mock

import pytest

from app.applications.communications import GmailApiProvider, MicrosoftGraphEmailProvider
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


def test_uncertain_email_action_timeout_is_audited_and_not_retried(database):
    provider = ActionProvider()
    provider.create_reply_draft = Mock(side_effect=TimeoutError("uncertain"))
    service = EmailActionService(database, provider)
    preview = service.prepare("reply", "message-1", "Reviewed reply")

    with pytest.raises(RuntimeError, match="inspect the provider before retrying"):
        service.execute(
            preview,
            confirmed=True,
            expected_digest=preview.digest,
        )
    provider.create_reply_draft.assert_called_once()
    with database.connect() as connection:
        results = [
            row[0]
            for row in connection.execute(
                "SELECT result FROM audit_logs ORDER BY rowid"
            )
        ]
    assert results[-2:] == ["provider_action_started", "unknown_after_timeout"]


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
