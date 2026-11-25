import pytest
from unittest.mock import Mock
import base64
from email import message_from_bytes

from app.applications.communications import (
    CommunicationService,
    GmailApiProvider,
    MicrosoftGraphEmailProvider,
    ProviderNotConfigured,
    WhatsAppCloudApiProvider,
    save_mail_attachment,
)
from database.database import Database


class FakeProvider:
    def __init__(self, error=None):
        self.calls = []
        self.draft_calls = []
        self.error = error

    def send(self, recipient, subject, body):
        self.calls.append((recipient, subject, body))
        if self.error:
            raise self.error
        return "external-id-1"

    def create_draft(self, recipient, subject, body, *, attachments=None):
        self.draft_calls.append((recipient, subject, body, attachments))
        if self.error:
            raise self.error
        return "provider-draft-id"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    return database


def test_communication_requires_exact_preview_and_confirmation(db):
    provider = FakeProvider()
    service = CommunicationService(db, email_provider=provider)
    draft_id = service.create_draft("email", "person@example.com", "Hello", subject="Hi")
    preview = service.preview(draft_id)

    with pytest.raises(PermissionError, match="confirmation"):
        service.send(draft_id, confirmed=False, expected_digest=preview.digest)
    with pytest.raises(PermissionError, match="changed"):
        service.send(draft_id, confirmed=True, expected_digest="wrong-preview")
    assert provider.calls == []

    external_id = service.send(
        draft_id,
        confirmed=True,
        expected_digest=preview.digest,
    )
    assert external_id == "external-id-1"
    assert service.status(draft_id) == "sent"
    assert provider.calls == [("person@example.com", "Hi", "Hello")]


def test_unconfigured_provider_keeps_draft_unsent(db):
    service = CommunicationService(db)
    draft_id = service.create_draft("whatsapp", "+14155550123", "Hi")
    preview = service.preview(draft_id)
    with pytest.raises(ProviderNotConfigured):
        service.send(draft_id, confirmed=True, expected_digest=preview.digest)
    assert service.status(draft_id) == "draft"


@pytest.mark.parametrize("recipient", ["14155550123", "+012345678", "+1234567"])
def test_whatsapp_drafts_reject_invalid_e164_recipients(db, recipient):
    service = CommunicationService(db)

    with pytest.raises(ValueError, match="E.164"):
        service.create_draft("whatsapp", recipient, "Hello")


def test_missing_token_keeps_reviewed_draft_retryable(db):
    provider = FakeProvider(error=ProviderNotConfigured("token missing"))
    service = CommunicationService(db, email_provider=provider)
    draft_id = service.create_draft("email", "person@example.com", "Hello")
    preview = service.preview(draft_id)

    with pytest.raises(ProviderNotConfigured):
        service.send(draft_id, confirmed=True, expected_digest=preview.digest)
    assert service.status(draft_id) == "draft"

    service.providers["email"] = FakeProvider()
    assert service.send(draft_id, confirmed=True, expected_digest=preview.digest)


def test_uncertain_timeout_cannot_be_resent(db):
    provider = FakeProvider(error=TimeoutError("uncertain"))
    service = CommunicationService(db, email_provider=provider)
    draft_id = service.create_draft("email", "person@example.com", "Hello")
    preview = service.preview(draft_id)

    with pytest.raises(RuntimeError, match="unknown"):
        service.send(draft_id, confirmed=True, expected_digest=preview.digest)
    assert service.status(draft_id) == "unknown"
    with pytest.raises(ValueError):
        service.send(draft_id, confirmed=True, expected_digest=preview.digest)
    assert len(provider.calls) == 1


def test_provider_email_draft_requires_exact_review_and_is_not_sent(db):
    provider = FakeProvider()
    service = CommunicationService(db, email_provider=provider)
    draft_id = service.create_draft(
        "email", "person@example.com", "Reviewed message", subject="Hello"
    )
    preview = service.preview(draft_id)

    with pytest.raises(PermissionError, match="explicit confirmation"):
        service.save_provider_draft(
            draft_id, confirmed=False, expected_digest=preview.digest
        )
    with pytest.raises(PermissionError, match="changed after preview"):
        service.save_provider_draft(
            draft_id, confirmed=True, expected_digest="wrong-digest"
        )
    assert provider.draft_calls == []

    provider_id = service.save_provider_draft(
        draft_id, confirmed=True, expected_digest=preview.digest
    )

    assert provider_id == "provider-draft-id"
    assert service.status(draft_id) == "provider_draft"
    assert provider.draft_calls == [
        ("person@example.com", "Hello", "Reviewed message", None)
    ]
    with db.connect() as connection:
        row = connection.execute(
            "SELECT external_id FROM communication_drafts WHERE draft_id=?",
            (draft_id,),
        ).fetchone()
    assert row["external_id"] == "provider-draft-id"
    with pytest.raises(ValueError, match="unsent draft"):
        service.preview(draft_id)


def test_whatsapp_cloud_api_provider_builds_documented_text_message(monkeypatch):
    response = Mock()
    response.json.return_value = {"messages": [{"id": "wamid.test-message"}]}
    post = Mock(return_value=response)
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    provider = WhatsAppCloudApiProvider(
        lambda: "test-access-token",
        "123456789012345",
        api_version="v27.0",
    )

    assert provider.send("+14155550123", "", "Hello") == "wamid.test-message"
    args, kwargs = post.call_args
    assert args[0] == "https://graph.facebook.com/v27.0/123456789012345/messages"
    assert kwargs["headers"]["Authorization"] == "Bearer test-access-token"
    assert kwargs["json"] == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "14155550123",
        "type": "text",
        "text": {"preview_url": False, "body": "Hello"},
    }


def test_whatsapp_provider_rejects_unvalidated_graph_url_parts():
    with pytest.raises(ValueError, match="phone number ID"):
        WhatsAppCloudApiProvider(lambda: "token", "123/../me", api_version="v27.0")
    with pytest.raises(ValueError, match="Graph API version"):
        WhatsAppCloudApiProvider(lambda: "token", "123456", api_version="v27.0/messages")


def test_email_providers_use_oauth_bearer_tokens_and_expected_endpoints(monkeypatch):
    gmail_response = Mock()
    gmail_response.json.return_value = {"id": "gmail-message-id"}
    graph_response = Mock()
    graph_response.headers = {"request-id": "graph-request-id"}
    post = Mock(side_effect=[gmail_response, graph_response])
    monkeypatch.setattr("app.applications.communications.httpx.post", post)

    gmail = GmailApiProvider(lambda: "gmail-test-token")
    graph = MicrosoftGraphEmailProvider(lambda: "graph-test-token")
    assert gmail.send("person@example.com", "Subject", "Body") == "gmail-message-id"
    assert graph.send("person@example.com", "Subject", "Body") == "graph-request-id"

    first, second = post.call_args_list
    assert first.args[0] == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    assert first.kwargs["headers"]["Authorization"] == "Bearer gmail-test-token"
    assert second.args[0] == "https://graph.microsoft.com/v1.0/me/sendMail"
    assert second.kwargs["headers"]["Authorization"] == "Bearer graph-test-token"


def test_email_providers_create_provider_side_drafts(monkeypatch):
    gmail_response = Mock()
    gmail_response.json.return_value = {"id": "gmail-draft-id"}
    graph_response = Mock()
    graph_response.json.return_value = {"id": "graph-draft-id"}
    post = Mock(side_effect=[gmail_response, graph_response])
    monkeypatch.setattr("app.applications.communications.httpx.post", post)

    gmail = GmailApiProvider(lambda: "gmail-test-token")
    graph = MicrosoftGraphEmailProvider(lambda: "graph-test-token")
    assert gmail.create_draft("person@example.com", "Hello", "Body") == "gmail-draft-id"
    assert graph.create_draft("person@example.com", "Hello", "Body") == "graph-draft-id"

    gmail_call, graph_call = post.call_args_list
    assert gmail_call.args[0] == "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
    assert gmail_call.kwargs["headers"]["Authorization"] == "Bearer gmail-test-token"
    raw = gmail_call.kwargs["json"]["message"]["raw"]
    mime = message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert mime["To"] == "person@example.com"
    assert mime["Subject"] == "Hello"
    assert mime.get_payload(decode=True).decode("utf-8").strip() == "Body"
    assert graph_call.args[0] == "https://graph.microsoft.com/v1.0/me/messages"
    assert graph_call.kwargs["headers"]["Authorization"] == "Bearer graph-test-token"
    assert graph_call.kwargs["json"] == {
        "subject": "Hello",
        "body": {"contentType": "Text", "content": "Body"},
        "toRecipients": [{"emailAddress": {"address": "person@example.com"}}],
    }


def test_email_providers_do_not_send_empty_credentials(monkeypatch):
    post = Mock()
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    with pytest.raises(ProviderNotConfigured):
        GmailApiProvider(lambda: "").send("person@example.com", "", "Hello")
    with pytest.raises(ProviderNotConfigured):
        MicrosoftGraphEmailProvider(lambda: "").send("person@example.com", "", "Hello")
    post.assert_not_called()


def test_gmail_search_and_read_return_bounded_untrusted_content(monkeypatch):
    plain = base64.urlsafe_b64encode(b"Hello from email").decode().rstrip("=")
    first = Mock()
    first.json.return_value = {"messages": [{"id": "mail-1", "threadId": "thread-1"}]}
    second = Mock()
    second.json.return_value = {
        "id": "mail-1",
        "threadId": "thread-1",
        "snippet": "Hello",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "A subject"},
                {"name": "From", "value": "person@example.com"},
            ],
            "mimeType": "text/plain",
            "body": {"data": plain},
        },
    }
    get = Mock(side_effect=[first, second])
    monkeypatch.setattr("app.applications.communications.httpx.get", get)
    provider = GmailApiProvider(lambda: "gmail-token")

    assert provider.search_messages("from:person@example.com", limit=5) == [
        {"id": "mail-1", "thread_id": "thread-1"}
    ]
    message = provider.read_message("mail-1")
    assert message["subject"] == "A subject"
    assert message["body"] == "Hello from email"
    assert message["trust"] == "untrusted_external_content"
    assert get.call_args_list[0].kwargs["params"] == {
        "maxResults": 5,
        "q": "from:person@example.com",
    }


def test_graph_search_read_and_attachment_download(monkeypatch):
    listed = Mock()
    listed.json.return_value = {
        "value": [
            {
                "id": "message-1",
                "subject": "Hello",
                "from": {"emailAddress": {"address": "sender@example.com"}},
                "bodyPreview": "preview",
                "hasAttachments": True,
            }
        ]
    }
    read = Mock()
    read.json.return_value = {
        "id": "message-1",
        "subject": "Hello",
        "from": {"emailAddress": {"address": "sender@example.com"}},
        "body": {"contentType": "text", "content": "Body"},
    }
    attachments = Mock()
    attachments.json.return_value = {
        "value": [
            {
                "id": "file-1",
                "name": "report.txt",
                "size": 4,
                "@odata.type": "#microsoft.graph.fileAttachment",
            }
        ]
    }
    file_response = Mock()
    file_response.json.return_value = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": "report.txt",
        "size": 4,
        "contentBytes": base64.b64encode(b"data").decode("ascii"),
    }
    get = Mock(side_effect=[listed, read, attachments, file_response])
    monkeypatch.setattr("app.applications.communications.httpx.get", get)
    provider = MicrosoftGraphEmailProvider(lambda: "graph-token")

    assert provider.search_messages("hello", limit=3)[0]["id"] == "message-1"
    assert provider.read_message("message-1")["body"] == "Body"
    assert provider.list_attachments("message-1")[0]["filename"] == "report.txt"
    assert provider.download_attachment("message-1", "file-1") == b"data"
    assert get.call_args_list[0].kwargs["headers"]["ConsistencyLevel"] == "eventual"


def test_email_attachment_save_is_approved_private_and_no_overwrite(tmp_path):
    with pytest.raises(PermissionError, match="explicit approval"):
        save_mail_attachment(b"data", "safe.txt", tmp_path)
    target = save_mail_attachment(
        b"data", "../../safe.txt", tmp_path / "attachments", approved=True
    )
    assert target.parent == (tmp_path / "attachments").resolve()
    assert target.name == "safe.txt"
    assert target.read_bytes() == b"data"
    with pytest.raises(FileExistsError, match="already exists"):
        save_mail_attachment(b"other", "safe.txt", tmp_path / "attachments", approved=True)


def test_email_attachment_is_part_of_approval_digest_and_must_not_change(db, tmp_path):
    exports = tmp_path / "exports"
    exports.mkdir()
    attachment = exports / "report.txt"
    attachment.write_bytes(b"original")
    provider = FakeProvider()
    service = CommunicationService(
        db,
        email_provider=provider,
        attachment_roots=[exports],
    )
    draft_id = service.create_draft(
        "email",
        "person@example.com",
        "See attached",
        subject="Report",
        attachments=[attachment],
    )
    preview = service.preview(draft_id)
    assert preview.attachments[0]["filename"] == "report.txt"
    assert preview.attachments[0]["sha256"]

    attachment.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed after the draft"):
        service.preview(draft_id)
    assert provider.calls == []


def test_email_send_passes_only_approved_attachment_bytes(db, tmp_path):
    exports = tmp_path / "exports"
    exports.mkdir()
    attachment = exports / "report.txt"
    attachment.write_bytes(b"private file")

    class AttachmentProvider:
        def __init__(self):
            self.calls = []

        def send(self, recipient, subject, body, *, attachments=None):
            self.calls.append((recipient, subject, body, attachments))
            return "sent-with-attachment"

    provider = AttachmentProvider()
    service = CommunicationService(db, email_provider=provider, attachment_roots=[exports])
    draft_id = service.create_draft(
        "email",
        "person@example.com",
        "See attached",
        subject="Report",
        attachments=[attachment],
    )
    preview = service.preview(draft_id)

    assert service.send(draft_id, confirmed=True, expected_digest=preview.digest) == "sent-with-attachment"
    assert provider.calls == [
        ("person@example.com", "Report", "See attached", [("report.txt", b"private file")])
    ]


def test_email_provider_encodes_attachments_for_each_mail_api(monkeypatch):
    gmail_response = Mock()
    gmail_response.json.return_value = {"id": "gmail-id"}
    graph_response = Mock()
    graph_response.headers = {"request-id": "graph-id"}
    post = Mock(side_effect=[gmail_response, graph_response])
    monkeypatch.setattr("app.applications.communications.httpx.post", post)

    gmail = GmailApiProvider(lambda: "gmail-token")
    graph = MicrosoftGraphEmailProvider(lambda: "graph-token")
    gmail.send("person@example.com", "Subject", "Body", attachments=[("report.txt", b"data")])
    graph.send("person@example.com", "Subject", "Body", attachments=[("report.txt", b"data")])

    gmail_raw = post.call_args_list[0].kwargs["json"]["raw"]
    raw_bytes = base64.urlsafe_b64decode(gmail_raw + "=" * (-len(gmail_raw) % 4))
    parsed = message_from_bytes(raw_bytes)
    attachments_found = [
        part.get_filename() for part in parsed.walk() if part.get_filename()
    ]
    assert attachments_found == ["report.txt"]
    graph_attachment = post.call_args_list[1].kwargs["json"]["message"]["attachments"][0]
    assert graph_attachment["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert base64.b64decode(graph_attachment["contentBytes"]) == b"data"


def test_graph_attachment_limit_fails_before_network_request(monkeypatch):
    post = Mock()
    monkeypatch.setattr("app.applications.communications.httpx.post", post)
    provider = MicrosoftGraphEmailProvider(lambda: "graph-token")
    with pytest.raises(ValueError, match="2 MB"):
        provider.send(
            "person@example.com",
            "Subject",
            "Body",
            attachments=[("large.bin", b"x" * 2_000_001)],
        )
    post.assert_not_called()
