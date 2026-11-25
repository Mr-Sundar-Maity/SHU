import pytest

from app.applications.contacts import (
    AmbiguousContactError,
    ContactBook,
    ContactNotFoundError,
)
from database.database import Database


@pytest.fixture
def contacts(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    return database, ContactBook(database)


def test_contact_book_resolves_exact_unicode_casefolded_name_and_number(contacts):
    _database, book = contacts
    saved = book.add("  José   Rivera ", "+14155550111", confirmed=True)

    assert book.resolve("JOSÉ rivera") == saved
    assert book.resolve("+14155550111") == saved
    direct = book.resolve("+14155550123")
    assert direct.contact_id is None
    assert direct.display_name is None
    assert direct.phone_e164 == "+14155550123"


def test_duplicate_names_require_explicit_disambiguation(contacts):
    _database, book = contacts
    book.add("Sam Lee", "+14155550123", confirmed=True)
    book.add("  sam   lee ", "+442079460123", confirmed=True)

    with pytest.raises(AmbiguousContactError) as error:
        book.resolve("SAM LEE")

    assert [match.phone_e164 for match in error.value.matches] == [
        "+14155550123",
        "+442079460123",
    ]


def test_unknown_name_is_not_guessed(contacts):
    _database, book = contacts

    with pytest.raises(ContactNotFoundError, match="exact name"):
        book.resolve("Sam")


def test_adding_contact_requires_confirmation(contacts):
    _database, book = contacts

    with pytest.raises(PermissionError, match="confirmation"):
        book.add("Sam Lee", "+14155550123")
    assert book.list_contacts() == []


@pytest.mark.parametrize(
    "phone",
    ["14155550123", "+012345678", "+1234567", "+1234567890123456", "+12 3456789"],
)
def test_contact_book_requires_valid_e164_number(contacts, phone):
    _database, book = contacts

    with pytest.raises(ValueError, match="E.164"):
        book.add("Sam Lee", phone, confirmed=True)


def test_contact_delete_requires_confirmation_and_audit_avoids_pii(contacts):
    database, book = contacts
    saved = book.add("Private Name", "+14155550123", confirmed=True)

    with pytest.raises(PermissionError, match="confirmation"):
        book.delete(saved.contact_id or "")
    book.delete(saved.contact_id or "", confirmed=True)

    assert book.list_contacts() == []
    with database.connect() as connection:
        logs = connection.execute(
            "SELECT action_summary,result FROM audit_logs WHERE actor='contact_book'"
        ).fetchall()
    assert [(row["result"], row["action_summary"]) for row in logs] == [
        ("contact_added", f"contact_id={saved.contact_id}"),
        ("contact_deleted", f"contact_id={saved.contact_id}"),
    ]
    assert all("Private Name" not in row["action_summary"] for row in logs)
    assert all("+14155550123" not in row["action_summary"] for row in logs)
