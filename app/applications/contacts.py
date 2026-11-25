"""Private, local-only contact book for explicit WhatsApp recipient resolution."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from database.database import Database


_E164 = re.compile(r"\+[1-9]\d{7,14}\Z")


@dataclass(frozen=True, slots=True)
class ContactRecord:
    contact_id: str | None
    display_name: str | None
    phone_e164: str


class ContactNotFoundError(LookupError):
    """A supplied name has no exact local contact match."""


class AmbiguousContactError(LookupError):
    """A supplied name matches multiple contacts and needs user disambiguation."""

    def __init__(self, matches: tuple[ContactRecord, ...]) -> None:
        self.matches = matches
        super().__init__("More than one contact has this name; choose a number explicitly")


class ContactBook:
    """Manage contacts locally; do not sync, infer, or send to contacts."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def add(
        self,
        display_name: str,
        phone_e164: str,
        *,
        confirmed: bool = False,
    ) -> ContactRecord:
        name, normalized = self._normalize_name(display_name)
        phone = self._validate_phone(phone_e164)
        if confirmed is not True:
            raise PermissionError("Adding a local contact requires explicit confirmation")
        contact_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            with connection:
                try:
                    connection.execute(
                        """INSERT INTO contacts(
                            contact_id,display_name,normalized_name,phone_e164,created_at,updated_at
                        ) VALUES(?,?,?,?,?,?)""",
                        (contact_id, name, normalized, phone, now, now),
                    )
                except sqlite3.IntegrityError as error:
                    raise ValueError("That WhatsApp number is already in the local contact book") from error
                self._audit(connection, contact_id, "contact_added", "confirmed")
        return ContactRecord(contact_id, name, phone)

    def list_contacts(self) -> list[ContactRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT contact_id,display_name,phone_e164 FROM contacts
                   ORDER BY normalized_name,phone_e164"""
            ).fetchall()
        return [self._record(row) for row in rows]

    def get(self, contact_id: str) -> ContactRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT contact_id,display_name,phone_e164 FROM contacts
                   WHERE contact_id=?""",
                (contact_id,),
            ).fetchone()
        return self._record(row) if row is not None else None

    def resolve(self, recipient: str) -> ContactRecord:
        """Resolve only an exact local name or a validated explicit phone number."""
        if not isinstance(recipient, str):
            raise ValueError("WhatsApp recipient must be text")
        value = recipient.strip()
        if value.startswith("+"):
            phone = self._validate_phone(value)
            with self.database.connect() as connection:
                row = connection.execute(
                    """SELECT contact_id,display_name,phone_e164 FROM contacts
                       WHERE phone_e164=?""",
                    (phone,),
                ).fetchone()
            return self._record(row) if row is not None else ContactRecord(None, None, phone)

        _display_name, normalized = self._normalize_name(value)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT contact_id,display_name,phone_e164 FROM contacts
                   WHERE normalized_name=? ORDER BY phone_e164""",
                (normalized,),
            ).fetchall()
        matches = tuple(self._record(row) for row in rows)
        if not matches:
            raise ContactNotFoundError("No local contact matches that exact name")
        if len(matches) > 1:
            raise AmbiguousContactError(matches)
        return matches[0]

    def delete(self, contact_id: str, *, confirmed: bool = False) -> None:
        if confirmed is not True:
            raise PermissionError("Deleting a local contact requires explicit confirmation")
        with self.database.connect() as connection:
            with connection:
                row = connection.execute(
                    "SELECT contact_id FROM contacts WHERE contact_id=?", (contact_id,)
                ).fetchone()
                if row is None:
                    raise KeyError("Contact not found")
                connection.execute("DELETE FROM contacts WHERE contact_id=?", (contact_id,))
                self._audit(connection, contact_id, "contact_deleted", "confirmed")

    @staticmethod
    def _normalize_name(value: str) -> tuple[str, str]:
        if not isinstance(value, str):
            raise ValueError("Contact name must be text")
        display_name = " ".join(unicodedata.normalize("NFKC", value).split())
        if (
            not display_name
            or len(display_name) > 120
            or any(ord(character) < 32 or ord(character) == 127 for character in display_name)
        ):
            raise ValueError("Contact name must contain 1-120 printable characters")
        return display_name, display_name.casefold()

    @staticmethod
    def _validate_phone(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("WhatsApp phone number must be text")
        phone = value.strip()
        if not _E164.fullmatch(phone):
            raise ValueError("WhatsApp phone must be a valid E.164 number, such as +14155550123")
        return phone

    @staticmethod
    def _record(row: sqlite3.Row) -> ContactRecord:
        return ContactRecord(
            contact_id=str(row["contact_id"]),
            display_name=str(row["display_name"]),
            phone_e164=str(row["phone_e164"]),
        )

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        contact_id: str,
        result: str,
        approval: str,
    ) -> None:
        connection.execute(
            """INSERT INTO audit_logs(
                log_id,actor,tool,action_summary,risk,approval,result,timestamp
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                "contact_book",
                "contacts",
                f"contact_id={contact_id}",
                "L1" if result == "contact_added" else "L2",
                approval,
                result,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
