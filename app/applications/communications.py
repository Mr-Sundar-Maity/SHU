"""Draft, preview and explicitly approved email/message delivery."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import mimetypes
import sqlite3
import re
import uuid
import os
from html.parser import HTMLParser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol
from urllib.parse import quote

import httpx

from app.automation.paths import PathPolicy
from database.database import Database


class DeliveryProvider(Protocol):
    def send(
        self,
        recipient: str,
        subject: str,
        body: str,
        *,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class DraftPreview:
    draft_id: str
    channel: str
    recipient: str
    subject: str
    body: str
    digest: str
    attachments: tuple[dict[str, object], ...] = ()


class ProviderNotConfigured(RuntimeError):
    pass


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip())


def _html_to_text(value: str) -> str:
    parser = _HTMLText()
    parser.feed(value)
    return "\n".join(parser.parts)


def _encoded_id(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f"{name} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{name} is invalid")
    return quote(value, safe="")


def _gmail_decode(data: str, *, max_bytes: int = 25_000_000) -> bytes:
    if not isinstance(data, str) or len(data) > max_bytes * 2:
        raise ValueError("Email attachment exceeds the local size limit")
    try:
        decoded = base64.b64decode(
            data + "=" * (-len(data) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as error:
        raise ValueError("Email attachment data is malformed") from error
    if len(decoded) > max_bytes:
        raise ValueError("Email attachment exceeds the local size limit")
    return decoded


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_mail_attachment(
    data: bytes,
    filename: str,
    attachment_dir: str | Path,
    *,
    approved: bool = False,
    max_bytes: int = 25_000_000,
) -> Path:
    """Save an approved external attachment into one private allowlisted folder."""
    if not approved:
        raise PermissionError("Saving an email attachment requires explicit approval")
    if not isinstance(filename, str) or len(filename) > 512:
        raise ValueError("Email attachment filename is invalid")
    if not isinstance(data, bytes) or len(data) > max_bytes:
        raise ValueError("Email attachment exceeds the local size limit")
    root = Path(attachment_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    raw_name = PureWindowsPath(PurePosixPath(filename).name).name
    cleaned = "".join(
        "_" if character in '<>:"/\\|?*' or ord(character) < 32 else character
        for character in raw_name
    ).strip().rstrip(" .")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "email-attachment.bin"
    if cleaned.split(".")[0].upper() in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        cleaned = "_" + cleaned
    cleaned = cleaned[:180]
    policy = PathPolicy([root])
    target = policy.resolve(root / cleaned)
    try:
        with target.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise FileExistsError("An attachment with this filename already exists") from None
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


class CommunicationService:
    """Never sends without exact-preview approval; uncertain sends are not retried."""

    def __init__(
        self,
        database: Database,
        *,
        email_provider: DeliveryProvider | None = None,
        whatsapp_provider: DeliveryProvider | None = None,
        attachment_roots: tuple[str | Path, ...] | list[str | Path] = (),
        timeout: float = 20.0,
    ) -> None:
        self.database = database
        self.providers = {"email": email_provider, "whatsapp": whatsapp_provider}
        self.timeout = timeout
        self.attachment_roots = tuple(Path(root).expanduser().resolve() for root in attachment_roots)
        self.attachment_paths = PathPolicy(self.attachment_roots) if self.attachment_roots else None

    def create_draft(
        self,
        channel: str,
        recipient: str,
        body: str,
        *,
        subject: str = "",
        attachments: tuple[str | Path, ...] | list[str | Path] = (),
    ) -> str:
        channel = channel.lower()
        if channel not in self.providers:
            raise ValueError("channel must be email or whatsapp")
        self._validate_recipient(channel, recipient)
        if not body or len(body) > 50_000:
            raise ValueError("Message body must contain 1-50000 characters")
        if len(subject) > 500 or "\n" in subject or "\r" in subject:
            raise ValueError("Email subject is invalid")
        if channel == "whatsapp" and subject:
            raise ValueError("WhatsApp drafts do not have a subject")
        if channel == "whatsapp" and attachments:
            raise ValueError("WhatsApp text drafts do not support attachments")
        attachment_records = self._prepare_attachments(attachments)
        draft_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    "INSERT INTO communication_drafts(draft_id,channel,recipient,subject,body,status,created_at,attachments_json) VALUES(?,?,?,?,?,'draft',?,?)",
                    (draft_id, channel, recipient.strip(), subject.strip(), body, now, json.dumps(attachment_records)),
                )
                self._audit(connection, draft_id, channel, "not_required", "draft_created")
        return draft_id

    def preview(self, draft_id: str) -> DraftPreview:
        row = self._get_draft(draft_id)
        if row["status"] != "draft":
            raise ValueError("Only an unsent draft can be previewed for approval")
        attachment_records = self._verified_attachment_records(row)
        attachment_metadata = [
            {
                "filename": item["filename"],
                "size": item["size"],
                "sha256": item["sha256"],
            }
            for item in attachment_records
        ]
        canonical = "\0".join(
            (
                row["channel"],
                row["recipient"],
                row["subject"],
                row["body"],
                json.dumps(attachment_metadata, ensure_ascii=False, sort_keys=True),
            )
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return DraftPreview(
            draft_id=row["draft_id"],
            channel=row["channel"],
            recipient=row["recipient"],
            subject=row["subject"],
            body=row["body"],
            digest=digest,
            attachments=tuple(attachment_metadata),
        )

    def send(
        self,
        draft_id: str,
        *,
        confirmed: bool,
        expected_digest: str,
    ) -> str:
        if not confirmed:
            raise PermissionError("Sending requires explicit confirmation")
        preview = self.preview(draft_id)
        if not hmac.compare_digest(preview.digest, expected_digest):
            raise PermissionError("The draft changed after preview; review it again")
        provider = self.providers[preview.channel]
        if provider is None:
            raise ProviderNotConfigured(
                f"The {preview.channel} provider and user authorization are not configured"
            )
        attachment_data = self._read_attachment_bytes(draft_id)
        provider_attachment_limit = getattr(provider, "max_attachment_bytes", None)
        if attachment_data and provider_attachment_limit is not None:
            if sum(len(data) for _name, data in attachment_data) > provider_attachment_limit:
                raise ValueError("Attachments exceed this email provider's direct-send limit")

        with self.database.connect() as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE communication_drafts SET status='sending',approved_at=? WHERE draft_id=? AND status='draft'",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), draft_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Draft is no longer available for sending")
                self._audit(connection, draft_id, preview.channel, "approved", "sending")

        try:
            if attachment_data:
                external_id = provider.send(
                    preview.recipient,
                    preview.subject,
                    preview.body,
                    attachments=attachment_data,
                )
            else:
                external_id = provider.send(
                    preview.recipient,
                    preview.subject,
                    preview.body,
                )
        except ProviderNotConfigured:
            # No request was made, so keep the reviewed draft available after
            # the user configures the missing credential.
            self._set_delivery(draft_id, "draft", "provider_not_configured")
            raise
        except (TimeoutError, httpx.TimeoutException) as error:
            self._set_delivery(draft_id, "unknown", type(error).__name__)
            raise RuntimeError(
                "Delivery status is unknown after timeout; do not retry automatically"
            ) from error
        except Exception as error:
            self._set_delivery(draft_id, "failed", type(error).__name__)
            raise

        self._set_delivery(draft_id, "sent", external_id[:500])
        return external_id

    def save_provider_draft(
        self,
        draft_id: str,
        *,
        confirmed: bool,
        expected_digest: str,
    ) -> str:
        """Create a provider-side email draft after exact-preview confirmation."""
        if not confirmed:
            raise PermissionError("Saving a provider draft requires explicit confirmation")
        preview = self.preview(draft_id)
        if preview.channel != "email":
            raise ValueError("Provider-side drafts are supported for email only")
        if not hmac.compare_digest(preview.digest, expected_digest):
            raise PermissionError("The draft changed after preview; review it again")
        provider = self.providers["email"]
        create_draft = getattr(provider, "create_draft", None)
        if not callable(create_draft):
            raise ProviderNotConfigured("The configured email provider cannot create drafts")
        attachments = self._read_attachment_bytes(draft_id)
        attachment_limit = getattr(provider, "max_attachment_bytes", None)
        if attachments and attachment_limit is not None:
            if sum(len(data) for _name, data in attachments) > attachment_limit:
                raise ValueError("Attachments exceed this email provider's draft limit")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE communication_drafts SET status='saving_provider_draft',approved_at=? "
                    "WHERE draft_id=? AND status='draft'",
                    (now, draft_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Draft is no longer available for provider-side saving")
                self._audit(connection, draft_id, "email", "approved", "saving_provider_draft")
        try:
            if attachments:
                provider_id = create_draft(
                    preview.recipient,
                    preview.subject,
                    preview.body,
                    attachments=attachments,
                )
            else:
                provider_id = create_draft(
                    preview.recipient,
                    preview.subject,
                    preview.body,
                )
            if not isinstance(provider_id, str) or not provider_id:
                raise RuntimeError("Email provider returned no draft ID")
        except ProviderNotConfigured:
            self._set_delivery(draft_id, "draft", "provider_not_configured")
            raise
        except Exception as error:
            self._set_delivery(draft_id, "unknown", type(error).__name__)
            raise RuntimeError(
                "Provider draft status is unknown; inspect the provider before retrying"
            ) from error

        self._set_delivery(draft_id, "provider_draft", provider_id[:500])
        return provider_id

    def status(self, draft_id: str) -> str:
        return str(self._get_draft(draft_id)["status"])

    def _get_draft(self, draft_id: str) -> sqlite3.Row:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM communication_drafts WHERE draft_id=?", (draft_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Communication draft not found")
        return row

    def _prepare_attachments(
        self,
        paths: tuple[str | Path, ...] | list[str | Path],
    ) -> list[dict[str, object]]:
        if not paths:
            return []
        if self.attachment_paths is None:
            raise ValueError("Email attachment storage roots are not configured")
        if len(paths) > 10:
            raise ValueError("A message cannot have more than 10 attachments")
        records: list[dict[str, object]] = []
        seen_paths: set[Path] = set()
        total_size = 0
        for value in paths:
            path = self.attachment_paths.resolve(value, must_exist=True)
            if path in seen_paths:
                raise ValueError("The same file cannot be attached more than once")
            seen_paths.add(path)
            if not path.is_file():
                raise ValueError("Email attachments must be regular files")
            if len(path.name) > 255 or any(ord(character) < 32 for character in path.name):
                raise ValueError("Email attachment filename is invalid")
            size = path.stat().st_size
            total_size += size
            if total_size > 15_000_000:
                raise ValueError("Email attachments exceed SHU's 15 MB total limit")
            records.append(
                {
                    "path": str(path),
                    "filename": path.name,
                    "size": size,
                    "sha256": _sha256_file(path),
                }
            )
        return records

    def _verified_attachment_records(self, row: sqlite3.Row) -> list[dict[str, object]]:
        try:
            records = json.loads(row["attachments_json"])
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("Email draft attachment data is invalid") from error
        if not isinstance(records, list) or len(records) > 10:
            raise ValueError("Email draft attachment list is invalid")
        if records and self.attachment_paths is None:
            raise ValueError("Email attachment storage roots are not configured")
        verified: list[dict[str, object]] = []
        total_size = 0
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise ValueError("Email draft attachment record is invalid")
            assert self.attachment_paths is not None
            path = self.attachment_paths.resolve(record["path"], must_exist=True)
            if not path.is_file() or path.name != record.get("filename"):
                raise ValueError("An email attachment is no longer available")
            size = path.stat().st_size
            digest = _sha256_file(path)
            if size != record.get("size") or digest != record.get("sha256"):
                raise ValueError("An email attachment changed after the draft was created")
            total_size += size
            if total_size > 15_000_000:
                raise ValueError("Email attachments exceed SHU's 15 MB total limit")
            verified.append({**record, "path": str(path)})
        return verified

    def _read_attachment_bytes(self, draft_id: str) -> list[tuple[str, bytes]]:
        row = self._get_draft(draft_id)
        result = []
        for record in self._verified_attachment_records(row):
            path = Path(str(record["path"]))
            data = path.read_bytes()
            if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("An email attachment changed after preview")
            result.append((str(record["filename"]), data))
        return result

    def _set_delivery(self, draft_id: str, status: str, result: str) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    "UPDATE communication_drafts SET status=?,sent_at=?,external_id=?,result=? WHERE draft_id=?",
                    (
                        status,
                        now if status == "sent" else None,
                        result if status in {"sent", "provider_draft"} else None,
                        result,
                        draft_id,
                    ),
                )
                self._audit(connection, draft_id, "communication", "approved", status)

    @staticmethod
    def _audit(connection: sqlite3.Connection, draft_id: str, channel: str, approval: str, result: str) -> None:
        connection.execute(
            """INSERT INTO audit_logs(log_id,actor,tool,action_summary,risk,approval,result,timestamp)
            VALUES(?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                "communication_service",
                channel,
                f"draft_id={draft_id}",
                "L3",
                approval,
                result,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )

    @staticmethod
    def _validate_recipient(channel: str, recipient: str) -> None:
        recipient = recipient.strip()
        if "\n" in recipient or "\r" in recipient or len(recipient) > 320:
            raise ValueError("Recipient is invalid")
        if channel == "email":
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient):
                raise ValueError("A valid email address is required")
        elif not re.fullmatch(r"\+[1-9]\d{7,14}", recipient):
            raise ValueError("WhatsApp recipient must use E.164 format, such as +14155550123")


class GmailApiProvider:
    """Gmail send adapter. Supply an OAuth token from a secure token store."""

    requires_forwarded_attachment_data = True

    def __init__(self, access_token: Callable[[], str], *, timeout: float = 20) -> None:
        self.access_token = access_token
        self.timeout = timeout

    def search_messages(self, query: str = "", *, limit: int = 20) -> list[dict[str, str]]:
        if len(query) > 500 or "\r" in query or "\n" in query:
            raise ValueError("Gmail search query is invalid")
        if not 1 <= limit <= 100:
            raise ValueError("Email result limit must be between 1 and 100")
        params: dict[str, str | int] = {"maxResults": limit}
        if query.strip():
            params["q"] = query.strip()
        response = httpx.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers={"Authorization": "Bearer " + self._token()},
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        messages = response.json().get("messages", [])
        if not isinstance(messages, list):
            raise RuntimeError("Gmail returned an invalid message list")
        return [
            {"id": str(item["id"]), "thread_id": str(item.get("threadId", ""))}
            for item in messages
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]

    def read_message(self, message_id: str) -> dict[str, object]:
        encoded = _encoded_id(message_id, "Gmail message ID")
        response = httpx.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{encoded}",
            headers={"Authorization": "Bearer " + self._token()},
            params={"format": "full"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Gmail returned an invalid message")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        headers = {
            str(item.get("name", "")).casefold(): str(item.get("value", ""))
            for item in payload.get("headers", [])
            if isinstance(item, dict)
        }
        plain_parts: list[str] = []
        html_parts: list[str] = []
        attachments: list[dict[str, object]] = []

        def visit(part: dict) -> None:
            mime_type = str(part.get("mimeType", ""))
            filename = str(part.get("filename", ""))
            part_body = part.get("body", {})
            if filename and part_body.get("attachmentId"):
                attachments.append(
                    {
                        "id": str(part_body["attachmentId"]),
                        "filename": filename,
                        "content_type": mime_type,
                        "size": int(part_body.get("size", 0) or 0),
                    }
                )
            elif mime_type == "text/plain" and part_body.get("data"):
                plain_parts.append(
                    _gmail_decode(part_body["data"], max_bytes=5_000_000).decode("utf-8", "replace")
                )
            elif mime_type == "text/html" and part_body.get("data"):
                html_parts.append(
                    _html_to_text(
                        _gmail_decode(part_body["data"], max_bytes=5_000_000).decode("utf-8", "replace")
                    )
                )
            for child in part.get("parts", []):
                if isinstance(child, dict):
                    visit(child)

        visit(payload)
        return {
            "id": str(data.get("id", message_id)),
            "thread_id": str(data.get("threadId", "")),
            "from": headers.get("from", ""),
            "reply_to": headers.get("reply-to", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "internet_message_id": headers.get("message-id", ""),
            "references": headers.get("references", ""),
            "snippet": str(data.get("snippet", ""))[:2_000],
            "body": "\n".join(plain_parts or html_parts)[:100_000],
            "attachments": attachments[:100],
            "trust": "untrusted_external_content",
        }

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        message = _encoded_id(message_id, "Gmail message ID")
        attachment = _encoded_id(attachment_id, "Gmail attachment ID")
        response = httpx.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
            f"{message}/attachments/{attachment}",
            headers={"Authorization": "Bearer " + self._token()},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("data"), str):
            raise RuntimeError("Gmail returned invalid attachment data")
        declared_size = int(data.get("size", 0) or 0)
        if declared_size > 25_000_000:
            raise ValueError("Email attachment exceeds the local size limit")
        return _gmail_decode(data["data"])

    def list_attachments(self, message_id: str) -> list[dict[str, object]]:
        result = self.read_message(message_id)
        return list(result["attachments"])

    def send(
        self,
        recipient: str,
        subject: str,
        body: str,
        *,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> str:
        token = self._token()
        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        for filename, data in attachments or []:
            mime_type, _encoding = mimetypes.guess_type(filename, strict=False)
            maintype, _, subtype = (mime_type or "application/octet-stream").partition("/")
            message.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype or "octet-stream",
                filename=filename,
            )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": "Bearer " + token},
            json={"raw": raw},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data.get("id"), str):
            raise RuntimeError("Gmail returned no delivery identifier")
        return data["id"]

    def create_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        *,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> str:
        """Save the reviewed message to the user's Gmail Drafts folder."""
        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        for filename, data in attachments or []:
            mime_type, _encoding = mimetypes.guess_type(filename, strict=False)
            maintype, _, subtype = (mime_type or "application/octet-stream").partition("/")
            message.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype or "octet-stream",
                filename=filename,
            )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
            headers={"Authorization": "Bearer " + self._token()},
            json={"message": {"raw": raw}},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise RuntimeError("Gmail returned no provider draft identifier")
        return data["id"]

    def create_reply_draft(
        self, message_id: str, recipient: str, subject: str, body: str
    ) -> str:
        source = self.read_message(message_id)
        message, thread_id = self._reply_message(source, recipient, subject, body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
            headers={"Authorization": "Bearer " + self._token()},
            json={"message": {"raw": raw, "threadId": thread_id}},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise RuntimeError("Gmail returned no reply draft identifier")
        return data["id"]

    def send_reply(
        self, message_id: str, recipient: str, subject: str, body: str
    ) -> str:
        source = self.read_message(message_id)
        message, thread_id = self._reply_message(source, recipient, subject, body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": "Bearer " + self._token()},
            json={"raw": raw, "threadId": thread_id},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise RuntimeError("Gmail returned no reply message identifier")
        return data["id"]

    def create_forward_draft(
        self,
        message_id: str,
        recipient: str,
        subject: str,
        body: str,
        *,
        source: dict[str, object],
        attachments: list[tuple[str, bytes]],
    ) -> str:
        del message_id
        message = self._forward_message(source, recipient, subject, body, attachments)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
            headers={"Authorization": "Bearer " + self._token()},
            json={"message": {"raw": raw}},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise RuntimeError("Gmail returned no forward draft identifier")
        return data["id"]

    def send_forward(
        self,
        message_id: str,
        recipient: str,
        subject: str,
        body: str,
        *,
        source: dict[str, object],
        attachments: list[tuple[str, bytes]],
    ) -> str:
        del message_id
        message = self._forward_message(source, recipient, subject, body, attachments)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": "Bearer " + self._token()},
            json={"raw": raw},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise RuntimeError("Gmail returned no forwarded message identifier")
        return data["id"]

    @staticmethod
    def _reply_message(
        source: dict[str, object], recipient: str, subject: str, body: str
    ) -> tuple[EmailMessage, str]:
        thread_id = str(source.get("thread_id", ""))
        message_id = str(source.get("internet_message_id", ""))
        references = str(source.get("references", ""))
        if not thread_id or not message_id:
            raise ValueError("The source email lacks Gmail thread or Message-ID headers")
        if any("\r" in value or "\n" in value for value in (message_id, references, subject)):
            raise ValueError("The source email has invalid reply headers")
        message = EmailMessage()
        message["To"] = recipient
        # Gmail requires the reply subject to match the source to keep the same thread.
        message["Subject"] = subject
        message["In-Reply-To"] = message_id
        message["References"] = (references + " " + message_id).strip()[-900:]
        message.set_content(body)
        return message, thread_id

    @staticmethod
    def _forward_message(
        source: dict[str, object],
        recipient: str,
        subject: str,
        body: str,
        attachments: list[tuple[str, bytes]],
    ) -> EmailMessage:
        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = subject
        source_headers = (
            ("From", source.get("from", "")),
            ("Date", source.get("date", source.get("received", ""))),
            ("Subject", source.get("subject", "")),
        )
        quote_lines = ["---------- Forwarded message ----------"]
        quote_lines.extend(f"{name}: {value}" for name, value in source_headers if value)
        quote_lines.extend(("", str(source.get("body", ""))))
        message.set_content(body.rstrip() + "\n\n" + "\n".join(quote_lines))
        total_size = 0
        for filename, data in attachments:
            if not filename or len(filename) > 255 or any(ord(char) < 32 for char in filename):
                raise ValueError("A source attachment has an invalid filename")
            total_size += len(data)
            if total_size > 15_000_000:
                raise ValueError("Source attachments exceed SHU's 15 MB forward limit")
            mime_type, _encoding = mimetypes.guess_type(filename, strict=False)
            maintype, _, subtype = (mime_type or "application/octet-stream").partition("/")
            message.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype or "octet-stream",
                filename=filename,
            )
        return message

    def _token(self) -> str:
        token = self.access_token()
        if not token or "\r" in token or "\n" in token:
            raise ProviderNotConfigured("Gmail OAuth access token is not available")
        return token


class MicrosoftGraphEmailProvider:
    """Microsoft Graph send adapter with an injected OAuth token provider."""

    max_attachment_bytes = 2_000_000

    def __init__(self, access_token: Callable[[], str], *, timeout: float = 20) -> None:
        self.access_token = access_token
        self.timeout = timeout

    def search_messages(self, query: str = "", *, limit: int = 20) -> list[dict[str, object]]:
        if len(query) > 500 or "\r" in query or "\n" in query:
            raise ValueError("Outlook search query is invalid")
        if not 1 <= limit <= 100:
            raise ValueError("Email result limit must be between 1 and 100")
        params = {
            "$top": limit,
            "$select": "id,subject,from,receivedDateTime,bodyPreview,hasAttachments",
            "$orderby": "receivedDateTime desc",
        }
        headers = {"Authorization": "Bearer " + self._token()}
        if query.strip():
            params["$search"] = '"' + query.strip().replace('"', "") + '"'
            headers["ConsistencyLevel"] = "eventual"
        response = httpx.get(
            "https://graph.microsoft.com/v1.0/me/messages",
            headers=headers,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        items = response.json().get("value", [])
        if not isinstance(items, list):
            raise RuntimeError("Microsoft Graph returned an invalid message list")
        return [
            {
                "id": str(item.get("id", "")),
                "subject": str(item.get("subject", "")),
                "from": str(item.get("from", {}).get("emailAddress", {}).get("address", "")),
                "received": str(item.get("receivedDateTime", "")),
                "preview": str(item.get("bodyPreview", ""))[:2_000],
                "has_attachments": bool(item.get("hasAttachments", False)),
            }
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]

    def read_message(self, message_id: str) -> dict[str, object]:
        encoded = _encoded_id(message_id, "Microsoft Graph message ID")
        response = httpx.get(
            f"https://graph.microsoft.com/v1.0/me/messages/{encoded}",
            headers={
                "Authorization": "Bearer " + self._token(),
                'Prefer': 'outlook.body-content-type="text"',
            },
            params={
                "$select": "id,subject,from,replyTo,toRecipients,receivedDateTime,"
                "conversationId,internetMessageId,body,hasAttachments"
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Microsoft Graph returned an invalid message")
        sender = data.get("from", {}).get("emailAddress", {}).get("address", "")
        body = data.get("body", {})
        content = str(body.get("content", "")) if isinstance(body, dict) else ""
        if isinstance(body, dict) and str(body.get("contentType", "")).casefold() == "html":
            content = _html_to_text(content)
        return {
            "id": str(data.get("id", message_id)),
            "from": str(sender),
            "reply_to": [
                str(item.get("emailAddress", {}).get("address", ""))
                for item in data.get("replyTo", [])
                if isinstance(item, dict)
            ],
            "to": [
                str(item.get("emailAddress", {}).get("address", ""))
                for item in data.get("toRecipients", [])
                if isinstance(item, dict)
            ],
            "subject": str(data.get("subject", "")),
            "received": str(data.get("receivedDateTime", "")),
            "thread_id": str(data.get("conversationId", "")),
            "internet_message_id": str(data.get("internetMessageId", "")),
            "body": content[:100_000],
            "has_attachments": bool(data.get("hasAttachments", False)),
            "trust": "untrusted_external_content",
        }

    def list_attachments(self, message_id: str) -> list[dict[str, object]]:
        encoded = _encoded_id(message_id, "Microsoft Graph message ID")
        response = httpx.get(
            f"https://graph.microsoft.com/v1.0/me/messages/{encoded}/attachments",
            headers={"Authorization": "Bearer " + self._token()},
            timeout=self.timeout,
        )
        response.raise_for_status()
        items = response.json().get("value", [])
        if not isinstance(items, list):
            raise RuntimeError("Microsoft Graph returned an invalid attachment list")
        return [
            {
                "id": str(item.get("id", "")),
                "filename": str(item.get("name", "attachment.bin")),
                "content_type": str(item.get("contentType", "application/octet-stream")),
                "size": int(item.get("size", 0) or 0),
                "is_inline": bool(item.get("isInline", False)),
                "type": str(item.get("@odata.type", "")),
            }
            for item in items
            if isinstance(item, dict)
        ][:100]

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        message = _encoded_id(message_id, "Microsoft Graph message ID")
        attachment = _encoded_id(attachment_id, "Microsoft Graph attachment ID")
        response = httpx.get(
            f"https://graph.microsoft.com/v1.0/me/messages/{message}/attachments/{attachment}",
            headers={"Authorization": "Bearer " + self._token()},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("@odata.type") != "#microsoft.graph.fileAttachment":
            raise ValueError("Only ordinary file attachments are supported")
        declared_size = int(data.get("size", 0) or 0)
        if declared_size > 25_000_000 or not isinstance(data.get("contentBytes"), str):
            raise ValueError("Email attachment exceeds the local size limit or is not downloadable")
        return _gmail_decode(data["contentBytes"])

    def send(
        self,
        recipient: str,
        subject: str,
        body: str,
        *,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> str:
        token = self._token()
        attachment_data = attachments or []
        if sum(len(data) for _name, data in attachment_data) > self.max_attachment_bytes:
            raise ValueError("Microsoft Graph direct attachments must total no more than 2 MB")
        graph_attachments = []
        for filename, data in attachment_data:
            mime_type, _encoding = mimetypes.guess_type(filename, strict=False)
            graph_attachments.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": filename,
                    "contentType": mime_type or "application/octet-stream",
                    "contentBytes": base64.b64encode(data).decode("ascii"),
                }
            )
        message = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }
        if graph_attachments:
            message["attachments"] = graph_attachments
        response = httpx.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers={"Authorization": "Bearer " + token},
            json={
                "message": message,
                "saveToSentItems": True,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.headers.get("request-id", "accepted")

    def create_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        *,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> str:
        """Create an unsent message in the user's Outlook Drafts folder."""
        attachment_data = attachments or []
        if sum(len(data) for _name, data in attachment_data) > self.max_attachment_bytes:
            raise ValueError("Microsoft Graph direct attachments must total no more than 2 MB")
        graph_attachments = []
        for filename, data in attachment_data:
            mime_type, _encoding = mimetypes.guess_type(filename, strict=False)
            graph_attachments.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": filename,
                    "contentType": mime_type or "application/octet-stream",
                    "contentBytes": base64.b64encode(data).decode("ascii"),
                }
            )
        message = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }
        if graph_attachments:
            message["attachments"] = graph_attachments
        response = httpx.post(
            "https://graph.microsoft.com/v1.0/me/messages",
            headers={"Authorization": "Bearer " + self._token()},
            json=message,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise RuntimeError("Microsoft Graph returned no provider draft identifier")
        return data["id"]

    def create_reply_draft(
        self, message_id: str, recipient: str, subject: str, body: str
    ) -> str:
        return self._create_verified_reply_draft(
            message_id, recipient, body, headers={"Authorization": "Bearer " + self._token()}
        )

    def _create_verified_reply_draft(
        self, message_id: str, recipient: str, body: str, *, headers: dict[str, str]
    ) -> str:
        encoded = _encoded_id(message_id, "Microsoft Graph message ID")
        recipients = {
            "toRecipients": [{"emailAddress": {"address": recipient}}],
            "ccRecipients": [],
            "bccRecipients": [],
        }
        response = httpx.post(
            f"https://graph.microsoft.com/v1.0/me/messages/{encoded}/createReply",
            headers=headers,
            json={"message": recipients, "comment": body},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        draft_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(draft_id, str) or not draft_id or draft_id == message_id:
            raise RuntimeError("Microsoft Graph returned no reply draft identifier")
        if data.get("isDraft") is False:
            raise RuntimeError("Microsoft Graph did not return an unsent reply draft")

        if not self._reply_recipients_match(data, recipient):
            # Graph may apply the source message's Reply-To list. Set the draft's
            # envelope explicitly and verify the returned message before sending.
            draft = _encoded_id(draft_id, "Microsoft Graph reply draft ID")
            updated = httpx.patch(
                f"https://graph.microsoft.com/v1.0/me/messages/{draft}",
                headers=headers,
                json=recipients,
                timeout=self.timeout,
            )
            updated.raise_for_status()
            data = updated.json()
            if (
                not isinstance(data, dict)
                or data.get("id") != draft_id
                or not self._reply_recipients_match(data, recipient)
            ):
                raise RuntimeError(
                    "Microsoft Graph did not confirm the reviewed reply recipient. "
                    "Inspect the unsent draft in Outlook."
                )
        return draft_id

    @staticmethod
    def _reply_recipients_match(data: dict, recipient: str) -> bool:
        to = data.get("toRecipients")
        if not isinstance(to, list) or len(to) != 1 or not isinstance(to[0], dict):
            return False
        address = to[0].get("emailAddress")
        return (
            data.get("isDraft") is True
            and isinstance(address, dict)
            and address.get("address") == recipient
            and data.get("ccRecipients") == []
            and data.get("bccRecipients") == []
        )

    def send_reply(
        self, message_id: str, recipient: str, subject: str, body: str
    ) -> str:
        headers = {"Authorization": "Bearer " + self._token()}
        draft_id = self._create_verified_reply_draft(message_id, recipient, body, headers=headers)
        encoded = _encoded_id(draft_id, "Microsoft Graph reply draft ID")
        response = httpx.post(
            f"https://graph.microsoft.com/v1.0/me/messages/{encoded}/send",
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.headers.get("request-id", "accepted")

    def create_forward_draft(
        self, message_id: str, recipient: str, subject: str, body: str
    ) -> str:
        del subject
        encoded = _encoded_id(message_id, "Microsoft Graph message ID")
        response = httpx.post(
            f"https://graph.microsoft.com/v1.0/me/messages/{encoded}/createForward",
            headers={"Authorization": "Bearer " + self._token()},
            json={
                "message": {
                    "toRecipients": [{"emailAddress": {"address": recipient}}]
                },
                "comment": body,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise RuntimeError("Microsoft Graph returned no forward draft identifier")
        return data["id"]

    def send_forward(
        self, message_id: str, recipient: str, subject: str, body: str
    ) -> str:
        del subject
        encoded = _encoded_id(message_id, "Microsoft Graph message ID")
        response = httpx.post(
            f"https://graph.microsoft.com/v1.0/me/messages/{encoded}/forward",
            headers={"Authorization": "Bearer " + self._token()},
            json={
                "message": {
                    "toRecipients": [{"emailAddress": {"address": recipient}}]
                },
                "comment": body,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.headers.get("request-id", "accepted")

    def _token(self) -> str:
        token = self.access_token()
        if not token or "\r" in token or "\n" in token:
            raise ProviderNotConfigured("Microsoft Graph access token is not available")
        return token


class WhatsAppCloudApiProvider:
    """Send approved text drafts through Meta's WhatsApp Business Cloud API."""

    def __init__(
        self,
        access_token: Callable[[], str],
        phone_number_id: str,
        *,
        api_version: str,
        timeout: float = 20.0,
    ) -> None:
        if not re.fullmatch(r"\d{5,32}", phone_number_id):
            raise ValueError("WhatsApp Business phone number ID is invalid")
        if not re.fullmatch(r"v\d+\.\d+", api_version):
            raise ValueError("Graph API version must look like v27.0")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.api_version = api_version
        self.timeout = timeout

    def send(
        self,
        recipient: str,
        subject: str,
        body: str,
        *,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> str:
        if subject:
            raise ValueError("WhatsApp text messages do not accept an email subject")
        if attachments:
            raise ValueError("WhatsApp text messages do not support file attachments")
        token = self.access_token()
        if not token or "\r" in token or "\n" in token:
            raise ProviderNotConfigured("WhatsApp Cloud API access token is not available")
        response = httpx.post(
            f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages",
            headers={"Authorization": "Bearer " + token},
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient.lstrip("+"),
                "type": "text",
                "text": {"preview_url": False, "body": body},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        try:
            message_id = response.json()["messages"][0]["id"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("WhatsApp Cloud API returned no message ID") from error
        if not isinstance(message_id, str) or not message_id:
            raise RuntimeError("WhatsApp Cloud API returned no message ID")
        return message_id
