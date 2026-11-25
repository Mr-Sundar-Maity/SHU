"""Exact-preview reply and forward actions for authorized email providers."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import getaddresses
from typing import Any

import httpx

from app.applications.communications import ProviderNotConfigured
from database.database import Database


@dataclass(frozen=True, slots=True)
class EmailActionPreview:
    action: str
    source_message_id: str
    source: dict[str, Any]
    source_attachments: tuple[dict[str, Any], ...]
    recipient: str
    subject: str
    comment: str
    source_fingerprint: str
    send: bool
    attachment_data: tuple[tuple[str, bytes], ...] = field(repr=False)

    @property
    def digest(self) -> str:
        metadata = {
            "action": self.action,
            "source_message_id": self.source_message_id,
            "source_fingerprint": self.source_fingerprint,
            "recipient": self.recipient,
            "subject": self.subject,
            "comment": self.comment,
            "send": self.send,
        }
        return hashlib.sha256(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()


class EmailActionService:
    """Prepare native provider reply/forward drafts with explicit review."""

    def __init__(self, database: Database, provider: Any) -> None:
        self.database = database
        self.provider = provider

    def prepare(
        self,
        action: str,
        source_message_id: str,
        comment: str,
        *,
        recipient: str | None = None,
        send: bool = False,
    ) -> EmailActionPreview:
        if action not in {"reply", "forward"}:
            raise ValueError("Email action must be reply or forward")
        if not isinstance(comment, str) or not comment.strip() or len(comment) > 50_000:
            raise ValueError("Email message must contain 1-50000 characters")
        source, source_attachments, attachment_data = self._read_source(
            action, source_message_id
        )
        if action == "reply":
            recipient = self._reply_recipient(source)
        else:
            recipient = self._validate_address(recipient)
        subject = str(source.get("subject", ""))
        if action == "forward":
            subject = "Fwd: " + subject if subject else "Forwarded message"
        if len(subject) > 500 or "\r" in subject or "\n" in subject:
            raise ValueError("Source email subject is invalid")

        source_fingerprint = self._fingerprint(
            source, source_attachments, attachment_data
        )
        return EmailActionPreview(
            action=action,
            source_message_id=source_message_id,
            source=source,
            source_attachments=tuple(source_attachments),
            recipient=recipient,
            subject=subject,
            comment=comment,
            source_fingerprint=source_fingerprint,
            send=send,
            attachment_data=tuple(attachment_data),
        )

    def execute(
        self,
        preview: EmailActionPreview,
        *,
        confirmed: bool,
        expected_digest: str,
        send: bool = False,
    ) -> str:
        if not confirmed:
            raise PermissionError("Email actions require explicit confirmation")
        if preview.send != send:
            raise PermissionError("The email delivery mode changed; review it again")
        if not isinstance(expected_digest, str) or not hmac.compare_digest(
            preview.digest, expected_digest
        ):
            raise PermissionError("The email preview changed; review it again")

        current = self.prepare(
            preview.action,
            preview.source_message_id,
            preview.comment,
            recipient=preview.recipient if preview.action == "forward" else None,
            send=send,
        )
        if not hmac.compare_digest(preview.source_fingerprint, current.source_fingerprint):
            raise PermissionError("The source email changed after preview; review it again")
        if not hmac.compare_digest(preview.digest, current.digest):
            raise PermissionError("The email action changed after preview; review it again")

        preview = current
        method_name = (
            f"send_{preview.action}"
            if send
            else f"create_{preview.action}_draft"
        )
        method = getattr(self.provider, method_name, None)
        if not callable(method):
            raise ProviderNotConfigured(
                f"The configured email provider does not support {preview.action}"
            )
        self._audit(preview, "approved", "provider_action_started", send=send)
        try:
            if preview.action == "reply":
                external_id = method(
                    preview.source_message_id,
                    preview.recipient,
                    preview.subject,
                    preview.comment,
                )
            elif getattr(self.provider, "requires_forwarded_attachment_data", False):
                external_id = method(
                    preview.source_message_id,
                    preview.recipient,
                    preview.subject,
                    preview.comment,
                    source=preview.source,
                    attachments=list(preview.attachment_data),
                )
            else:
                external_id = method(
                    preview.source_message_id,
                    preview.recipient,
                    preview.subject,
                    preview.comment,
                )
            if not isinstance(external_id, str) or not external_id:
                raise RuntimeError("Email provider returned no action identifier")
        except (TimeoutError, httpx.TimeoutException) as error:
            self._audit(preview, "approved", "unknown_after_timeout", send=send)
            raise RuntimeError(
                "Email action status is unknown after timeout; inspect the provider before retrying"
            ) from error
        except ProviderNotConfigured:
            self._audit(preview, "approved", "provider_not_configured", send=send)
            raise
        except Exception as error:
            self._audit(
                preview,
                "approved",
                "failed:" + type(error).__name__,
                send=send,
            )
            raise
        self._audit(
            preview,
            "approved",
            "sent" if send else "provider_draft_created",
            send=send,
            external_id=external_id,
        )
        return external_id

    def _read_source(
        self, action: str, message_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[tuple[str, bytes]]]:
        source = self.provider.read_message(message_id)
        if not isinstance(source, dict) or str(source.get("id", message_id)) != message_id:
            raise ValueError("Email provider returned a mismatched source message")
        attachments: list[dict[str, Any]] = []
        attachment_data: list[tuple[str, bytes]] = []
        if action == "forward":
            list_attachments = getattr(self.provider, "list_attachments", None)
            if not callable(list_attachments):
                raise ProviderNotConfigured("The email provider cannot inspect attachments")
            attachments = list_attachments(message_id)
            if not isinstance(attachments, list) or len(attachments) > 100:
                raise ValueError("The source email attachment list is invalid")
            if getattr(self.provider, "requires_forwarded_attachment_data", False):
                if len(attachments) > 10:
                    raise ValueError("SHU forwards at most 10 source attachments")
                download = getattr(self.provider, "download_attachment", None)
                if not callable(download):
                    raise ProviderNotConfigured("The email provider cannot read attachments")
                total_size = 0
                for item in attachments:
                    if not isinstance(item, dict):
                        raise ValueError("The source email has invalid attachment metadata")
                    filename = str(item.get("filename", ""))
                    size = int(item.get("size", 0) or 0)
                    if not filename or size < 0 or size > 15_000_000:
                        raise ValueError("A source attachment is outside SHU's forward limits")
                    total_size += size
                    if total_size > 15_000_000:
                        raise ValueError("Source attachments exceed SHU's 15 MB forward limit")
                    data = download(message_id, str(item["id"]))
                    if len(data) != size:
                        raise ValueError("A source attachment changed while preparing the forward")
                    attachment_data.append((filename, data))
        return source, attachments, attachment_data

    @staticmethod
    def _reply_recipient(source: dict[str, Any]) -> str:
        reply_to = source.get("reply_to")
        candidates = reply_to if isinstance(reply_to, list) else [reply_to]
        candidates = [str(value) for value in candidates if value]
        candidates += [str(source.get("from", ""))]
        for candidate in candidates:
            addresses = [address for _name, address in getaddresses([candidate]) if address]
            if addresses:
                return EmailActionService._validate_address(addresses[0])
        raise ValueError("The source email has no valid reply recipient")

    @staticmethod
    def _validate_address(value: str | None) -> str:
        if not isinstance(value, str) or "\r" in value or "\n" in value:
            raise ValueError("A valid email address is required")
        addresses = [address for _name, address in getaddresses([value]) if address]
        if len(addresses) != 1 or not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", addresses[0]
        ):
            raise ValueError("A valid single email address is required")
        return addresses[0]

    @staticmethod
    def _fingerprint(
        source: dict[str, Any],
        attachments: list[dict[str, Any]],
        attachment_data: list[tuple[str, bytes]],
    ) -> str:
        fields = (
            "id", "thread_id", "internet_message_id", "references", "from", "reply_to",
            "to", "subject", "date", "received", "body", "has_attachments",
        )
        canonical = {
            "source": {key: source.get(key) for key in fields},
            "attachments": attachments,
            "attachment_hashes": [
                {"filename": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in attachment_data
            ],
        }
        return hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    def _audit(
        self,
        preview: EmailActionPreview,
        approval: str,
        result: str,
        *,
        send: bool,
        external_id: str = "",
    ) -> None:
        summary = (
            f"action={preview.action}; source={preview.source_message_id}; "
            f"recipient={preview.recipient}; digest={preview.digest}; "
            f"mode={'send' if send else 'provider_draft'}"
        )
        if external_id:
            summary += "; external_id=" + external_id[:300]
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    """INSERT INTO audit_logs(log_id,actor,tool,action_summary,risk,approval,result,timestamp)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()),
                        "email_action_service",
                        "email_" + preview.action,
                        summary,
                        "L3",
                        approval,
                        result,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    ),
                )
