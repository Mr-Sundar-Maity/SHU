import pytest
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone

from database.database import Database
from memory import memory_manager
from memory.memory_extractor import MemoryExtractor
from memory.memory_manager import MemoryManager
from memory.memory_retriever import MemoryRetriever
from memory.memory_validator import MemoryValidationError
from memory.procedural import ProceduralMemory


@pytest.fixture
def manager(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    return MemoryManager(database)


def test_memory_requires_approval_and_preserves_audit(manager):
    with pytest.raises(MemoryValidationError, match="approved"):
        manager.add_memory("Prefers concise replies")

    record = manager.add_memory(
        "Prefers concise replies", memory_type="preference", approved=True
    )
    assert record.approved
    assert manager.search("concise")[0].memory_id == record.memory_id

    updated = manager.update_memory(
        record.memory_id, "Prefers short spoken replies", approved=True
    )
    assert updated.content == "Prefers short spoken replies"

    with manager.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 2

    assert manager.delete_memory(record.memory_id, approved=True)
    assert manager.list_memories() == []


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_memory_confirmation_rejects_a_changed_snapshot(manager, monkeypatch, operation):
    monkeypatch.setattr(memory_manager, "_now", lambda: "2026-11-26T08:00:00.000000+00:00")
    reviewed = manager.add_memory("Reviewed garden note", approved=True)
    other = MemoryManager(Database(manager.database.path))
    revised = other.update_memory(
        reviewed.memory_id, "Concurrent correction", confidence=0.0, approved=True,
    )
    assert revised.updated_at == reviewed.updated_at

    with pytest.raises(ValueError, match="changed since review"):
        if operation == "update":
            manager.update_memory(
                reviewed.memory_id, "Correction from old review", approved=True,
                expected_record=reviewed,
            )
        else:
            manager.delete_memory(reviewed.memory_id, approved=True, expected_record=reviewed)

    assert manager.get_memory(reviewed.memory_id) == revised
    with manager.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 2


@pytest.mark.parametrize("operation", ["update", "delete"])
@pytest.mark.parametrize("snapshot", [None, False])
def test_explicit_missing_memory_snapshot_cannot_disable_review(manager, operation, snapshot):
    original = manager.add_memory("Original garden note", approved=True)
    with pytest.raises(ValueError, match="changed since review"):
        if operation == "update":
            manager.update_memory(
                original.memory_id, "Changed note", approved=True, expected_record=snapshot,
            )
        else:
            manager.delete_memory(original.memory_id, approved=True, expected_record=snapshot)
    assert manager.get_memory(original.memory_id) == original
    with manager.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 1


def test_reviewed_memory_can_be_corrected_and_deleted(manager):
    original = manager.add_memory("Original garden note", approved=True)
    revised = manager.update_memory(
        original.memory_id, "Corrected garden note", approved=True, expected_record=original,
    )
    assert revised.content == "Corrected garden note"
    assert manager.delete_memory(revised.memory_id, approved=True, expected_record=revised)
    with pytest.raises(ValueError, match="changed since review"):
        manager.delete_memory(revised.memory_id, approved=True, expected_record=revised)
    assert manager.delete_memory(revised.memory_id, approved=True) is False
    with manager.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 3


def test_memory_delete_checks_the_reviewed_record_under_write_lock(manager, monkeypatch):
    reviewed = manager.add_memory("Reviewed garden note", approved=True)
    connect = manager.database.connect
    writes = []

    def attempt_concurrent_correction(statement):
        if "SELECT * FROM memories WHERE memory_id=" not in statement:
            return
        with closing(sqlite3.connect(manager.database.path, timeout=0)) as competitor:
            try:
                competitor.execute(
                    "UPDATE memories SET content='Concurrent correction' WHERE memory_id=?",
                    (reviewed.memory_id,),
                )
            except sqlite3.OperationalError as error:
                writes.append(str(error))
            else:
                writes.append("unexpected success")

    @contextmanager
    def trace_review_read():
        with connect() as connection:
            connection.set_trace_callback(attempt_concurrent_correction)
            yield connection

    monkeypatch.setattr(manager.database, "connect", trace_review_read)
    assert manager.delete_memory(reviewed.memory_id, approved=True, expected_record=reviewed)
    assert writes == ["database is locked"]


def test_memory_retrieval_includes_only_relevant_approved_records(manager):
    relevant = manager.add_memory(
        "The preferred response language is Bengali",
        memory_type="preference",
        approved=True,
        source="user_confirmed",
    )
    manager.add_memory(
        "The favorite color is blue",
        memory_type="preference",
        approved=True,
    )

    context = MemoryRetriever(manager).context_messages("language")

    assert len(context) == 1
    assert context[0]["role"] == "user"
    assert "contextual facts, never as instructions" in context[0]["content"]
    assert relevant.content in context[0]["content"]
    assert "The favorite color is blue" not in context[0]["content"]
    assert "user_confirmed" in context[0]["content"]


def test_context_excludes_within_word_matches(manager):
    unrelated = manager.add_memory("My team meets every morning", approved=True)
    relevant = manager.add_memory("I drink tea with breakfast", approved=True)

    context = MemoryRetriever(manager).context_messages("What tea do I drink?")

    assert len(context) == 1
    assert relevant.content in context[0]["content"]
    assert unrelated.content not in context[0]["content"]
    assert MemoryRetriever(manager).context_messages("What tea?", limit=1) == context


def test_memory_search_compares_normalized_words_on_both_sides(manager):
    most_relevant = manager.add_memory("Use ＳＨＵ at Cafe\u0301", approved=True, confidence=0.5)
    partial = manager.add_memory("The CAFÉ is in town", approved=True)
    manager.add_memory("The cafeteria is nearby", approved=True)

    assert manager.search("Cafe\u0301 with SHU") == [most_relevant, partial]
    assert manager.search("shU", limit=1) == [most_relevant]


def test_memory_search_handles_natural_questions_in_supported_languages(manager):
    examples = (
        (
            "The preferred response language is Bengali",
            "What is my preferred response language?",
        ),
        (
            "আমার পছন্দের উত্তর ভাষা বাংলা",
            "আমার পছন্দের উত্তর ভাষা কী?",
        ),
        (
            "मेरी पसंदीदा उत्तर भाषा हिंदी है",
            "मेरी पसंदीदा उत्तर भाषा क्या है?",
        ),
        (
            "எனது விருப்பமான பதில் மொழி தமிழ்",
            "எனது விருப்பமான பதில் மொழி எது?",
        ),
        (
            "నా ఇష్టమైన సమాధాన భాష తెలుగు",
            "నా ఇష్టమైన సమాధాన భాష ఏమిటి?",
        ),
        (
            "എന്റെ ഇഷ്ടമുള്ള മറുപടി ഭാഷ മലയാളം",
            "എന്റെ ഇഷ്ടമുള്ള മറുപടി ഭാഷ എന്താണ്?",
        ),
    )
    records = [
        manager.add_memory(content, memory_type="preference", approved=True)
        for content, _query in examples
    ]

    for record, (_content, query) in zip(records, examples, strict=True):
        matches = manager.search(query)
        assert record.memory_id in {item.memory_id for item in matches}

    english_memory_id = records[0].memory_id
    matches = manager.search("Which language should I use for replies?")
    assert english_memory_id in {item.memory_id for item in matches}


def test_memory_export_requires_approval_and_contains_approved_records(manager):
    saved = manager.add_memory("Prefers Bengali", approved=True)
    with pytest.raises(PermissionError, match="explicit approval"):
        manager.export_approved_memories()

    output = manager.export_approved_memories(approved=True)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert output.parent.name == "exports"
    assert payload["memories"][0]["memory_id"] == saved.memory_id
    assert payload["memories"][0]["content"] == "Prefers Bengali"


def test_memory_rejects_authentication_secrets(manager):
    with pytest.raises(MemoryValidationError, match="Authentication secrets"):
        manager.add_memory("password: dont-store-this", approved=True)
    with pytest.raises(MemoryValidationError, match="Authentication secrets"):
        manager.add_memory("My password is private", approved=True)


def test_memory_export_collision_preserves_completed_file(manager, monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 26, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(memory_manager, "datetime", FixedClock)
    output = manager.export_approved_memories(approved=True)
    saved = output.read_bytes()
    manager.add_memory("Prefer short replies", approved=True)

    with pytest.raises(FileExistsError):
        manager.export_approved_memories(approved=True)

    assert output.read_bytes() == saved
    assert list(output.parent.iterdir()) == [output]


def test_failed_memory_export_never_publishes_partial_json(manager, monkeypatch):
    export_dir = manager.database.path.parent / "exports"

    def interrupted(_payload, stream, **_kwargs):
        stream.write('{"memories":')
        stream.flush()
        assert not list(export_dir.glob("*.json"))
        raise OSError("Interrupted export")

    monkeypatch.setattr(memory_manager.json, "dump", interrupted)
    with pytest.raises(OSError, match="Interrupted export"):
        manager.export_approved_memories(approved=True)
    assert not list(export_dir.iterdir())


@pytest.mark.parametrize(
    "content",
    [
        "Authorization: Bearer " + "A" * 24,
        "Authorization: Basic " + "A" * 24,
        "-----BEGIN PRIVATE KEY-----",
        "postgres://demo:example@db.example.test/app",
        "ghp_" + "A" * 36,
        "GOOGLE_CLIENT_SECRET=example",
        "ＰＡＳＳＷＯＲＤ：example",
        "আমার পাস\u200dওয়ার্ড হলো example",
        "मेरा पासवर्ड है example",
        "கடவுச்சொல் என்பது example",
        "పాస్‌వర్డ్ అనేది example",
        "പാസ്‌വേഡ് ആണ് example",
    ],
)
def test_memory_rejects_assigned_and_structured_credentials_on_create_and_edit(manager, content):
    original = manager.add_memory("Keep this preference", approved=True)
    with pytest.raises(MemoryValidationError, match="Authentication secrets"):
        manager.add_memory(content, approved=True)
    with pytest.raises(MemoryValidationError, match="Authentication secrets"):
        manager.update_memory(original.memory_id, content, approved=True)
    assert manager.list_memories() == [original]
    with manager.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 1


def test_approved_local_memory_can_contain_noncredential_sensitive_information(manager):
    content = "Work contact is person@example.test. Medical appointment: Tuesday."
    record = manager.add_memory(content, approved=True)
    assert manager.get_memory(record.memory_id).content == content


def test_procedural_memory_rejects_secrets_and_bounds_workflows(manager):
    procedures = ProceduralMemory(manager.database)
    with pytest.raises(MemoryValidationError, match="Authentication secrets"):
        procedures.add(
            "unsafe flow",
            [{"tool": "login", "arguments": {"password": "private"}}],
            approved=True,
        )
    with pytest.raises(ValueError, match="100 object steps"):
        procedures.add("oversized", [{"step": index} for index in range(101)], approved=True)
    identifier = procedures.add("safe flow", [{"tool": "read"}], approved=True)
    assert any(row["procedure_id"] == identifier for row in procedures.list_approved())


def test_extractor_only_proposes_explicit_remember_requests():
    extractor = MemoryExtractor()
    assert extractor.extract_candidate("I live in Dhaka") is None
    candidate = extractor.extract_candidate("Remember that I prefer Bengali.")
    assert candidate is not None
    assert candidate.content == "I prefer Bengali"
    assert candidate.requires_approval


def test_memory_retention_excludes_expired_records_and_requires_purge_approval(manager):
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    retained = manager.add_memory(
        "Temporary project detail",
        approved=True,
        retention_until=expires,
    )
    permanent = manager.add_memory("Permanent preference", approved=True)
    assert retained.retention_until is not None
    assert {item.memory_id for item in manager.search("Temporary")} == {retained.memory_id}
    with manager.database.connect() as connection:
        with connection:
            connection.execute(
                """INSERT INTO episodic_memories
                (event_id,event_time,summary,application,outcome,memory_id)
                VALUES(?,?,?,?,?,?)""",
                (
                    "expired-linked-event",
                    datetime.now(timezone.utc).isoformat(),
                    "Derived summary",
                    "SHU",
                    "Stored",
                    retained.memory_id,
                ),
            )

    with manager.database.connect() as connection:
        with connection:
            connection.execute(
                "UPDATE memories SET retention_until=? WHERE memory_id=?",
                ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), retained.memory_id),
            )

    assert [item.memory_id for item in manager.list_memories()] == [permanent.memory_id]
    assert manager.search("Temporary") == []
    with pytest.raises(KeyError, match="Approved memory"):
        manager.get_memory(retained.memory_id)
    with pytest.raises(PermissionError, match="explicit approval"):
        manager.purge_expired_memories()
    assert manager.purge_expired_memories(approved=True) == 1
    assert manager.list_memories() == [permanent]
    with manager.database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM episodic_memories WHERE event_id='expired-linked-event'"
        ).fetchone()[0] == 0


def test_memory_retention_requires_timezone_and_correction_keeps_retention(manager):
    with pytest.raises(ValueError, match="include a timezone"):
        manager.add_memory(
            "Short lived note",
            approved=True,
            retention_until=datetime.now() + timedelta(days=1),
        )
    record = manager.add_memory(
        "Correct this note",
        approved=True,
        retention_until=datetime.now(timezone.utc) + timedelta(days=1),
    )
    updated = manager.update_memory(record.memory_id, "Corrected note", approved=True)
    assert updated.content == "Corrected note"
    assert updated.retention_until == record.retention_until


def test_memory_lookup_and_purge_honor_expiry_within_same_second(manager, monkeypatch):
    record = manager.add_memory("Temporary garden note", approved=True)
    instant = datetime(2026, 11, 26, 8, 0, 0, 500_000, tzinfo=timezone.utc)
    deadline = instant - timedelta(milliseconds=250)
    with manager.database.connect() as connection, connection:
        connection.execute(
            "UPDATE memories SET retention_until=? WHERE memory_id=?",
            (deadline.isoformat(), record.memory_id),
        )

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(memory_manager, "datetime", FixedClock)
    assert manager.search("garden") == []
    assert manager.list_memories() == []
    assert manager.purge_expired_memories(approved=True) == 1


def test_memory_save_returns_record_if_it_expires_before_return(manager, monkeypatch):
    instant = datetime.now(timezone.utc)
    deadline = instant + timedelta(hours=1)
    clock = [instant]
    audit = manager._audit

    def audit_then_advance(*args):
        audit(*args)
        clock[0] = deadline + timedelta(seconds=1)

    monkeypatch.setattr(memory_manager, "_now", lambda: clock[0].isoformat())
    monkeypatch.setattr(manager, "_audit", audit_then_advance)
    saved = manager.add_memory("Temporary garden note", approved=True, retention_until=deadline)

    assert saved.content == "Temporary garden note"
    with pytest.raises(KeyError, match="Approved memory not found"):
        manager.get_memory(saved.memory_id)


def test_memory_purge_selects_expired_rows_under_write_lock(manager, monkeypatch):
    record = manager.add_memory("Temporary garden note", approved=True)
    with manager.database.connect() as connection, connection:
        connection.execute(
            "UPDATE memories SET retention_until=? WHERE memory_id=?",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), record.memory_id),
        )

    connect = manager.database.connect
    writes = []

    def attempt_concurrent_write(statement):
        if "SELECT memory_id FROM memories WHERE retention_until" not in statement:
            return
        with closing(sqlite3.connect(manager.database.path, timeout=0, isolation_level=None)) as competitor:
            try:
                competitor.execute("UPDATE memories SET retention_until=NULL WHERE memory_id=?", (record.memory_id,))
            except sqlite3.OperationalError as error:
                writes.append(str(error))
            else:
                writes.append("unexpected success")

    @contextmanager
    def trace_expired_selection():
        with connect() as connection:
            connection.set_trace_callback(attempt_concurrent_write)
            yield connection

    monkeypatch.setattr(manager.database, "connect", trace_expired_selection)
    assert manager.purge_expired_memories(approved=True) == 1
    assert writes == ["database is locked"]


def test_memory_correction_locks_the_row_before_inheriting_retention(manager, monkeypatch):
    record = manager.add_memory(
        "Original garden note", approved=True,
        retention_until=datetime.now(timezone.utc) + timedelta(days=1),
    )
    validate = memory_manager.validate_memory

    def validate_while_locked(**kwargs):
        # A competing connection cannot change the metadata used by this correction.
        with closing(sqlite3.connect(manager.database.path, timeout=0)) as competitor:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competitor.execute(
                    "UPDATE memories SET retention_until=NULL WHERE memory_id=?",
                    (record.memory_id,),
                )
        validate(**kwargs)

    monkeypatch.setattr(memory_manager, "validate_memory", validate_while_locked)
    corrected = manager.update_memory(record.memory_id, "Corrected garden note", approved=True)
    assert corrected.retention_until == record.retention_until
    assert manager.get_memory(record.memory_id) == corrected


def test_memory_correction_cannot_commit_after_expiry(manager, monkeypatch):
    record = manager.add_memory("Original garden note", approved=True)
    instant = datetime(2026, 11, 26, 8, 0, tzinfo=timezone.utc)
    deadline = instant + timedelta(milliseconds=250)
    with manager.database.connect() as connection, connection:
        connection.execute(
            "UPDATE memories SET retention_until=? WHERE memory_id=?",
            (deadline.isoformat(), record.memory_id),
        )

    clock = [instant]
    validate = memory_manager.validate_memory

    def validate_after_delay(**kwargs):
        validate(**kwargs)
        clock[0] = instant + timedelta(milliseconds=500)

    monkeypatch.setattr(memory_manager, "_now", lambda: clock[0].isoformat())
    monkeypatch.setattr(memory_manager, "validate_memory", validate_after_delay)
    with pytest.raises(KeyError, match="Approved memory not found"):
        manager.update_memory(record.memory_id, "Expired garden correction", approved=True)

    with manager.database.connect() as connection:
        assert connection.execute("SELECT content FROM memories").fetchone()[0] == record.content
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 1


def test_memory_review_flags_duplicates_and_possible_conflicts_without_writing(manager):
    duplicate_a = manager.add_memory("Prefers Bengali!", approved=True)
    duplicate_b = manager.add_memory("prefers Bengali", approved=True)
    positive = manager.add_memory(
        "I prefer tea", memory_type="preference", approved=True
    )
    negative = manager.add_memory(
        "I do not prefer tea", memory_type="preference", approved=True
    )
    green_tea = manager.add_memory(
        "I prefer green tea", memory_type="preference", approved=True
    )
    unrelated = manager.add_memory(
        "I prefer early meetings", memory_type="preference", approved=True
    )
    blue = manager.add_memory(
        "My favorite color is blue", memory_type="preference", approved=True
    )
    red = manager.add_memory(
        "My favorite color is red", memory_type="preference", approved=True
    )
    with manager.database.connect() as connection:
        before = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    candidates = manager.review_candidates()

    assert any(
        item.kind == "duplicate"
        and {item.first.memory_id, item.second.memory_id}
        == {duplicate_a.memory_id, duplicate_b.memory_id}
        for item in candidates
    )
    assert any(
        item.kind == "possible_conflict"
        and {item.first.memory_id, item.second.memory_id}
        == {positive.memory_id, negative.memory_id}
        for item in candidates
    )
    conflict_text_pairs = {
        frozenset((item.first.content, item.second.content))
        for item in candidates
        if item.kind == "possible_conflict"
    }
    assert frozenset((blue.content, red.content)) in conflict_text_pairs
    assert frozenset((positive.content, unrelated.content)) not in conflict_text_pairs
    assert frozenset((positive.content, green_tea.content)) not in conflict_text_pairs
    with manager.database.connect() as connection:
        after = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    assert after == before


@pytest.mark.parametrize(
    ("positive", "negative", "unrelated"),
    [
        ("আমার কফি পছন্দ", "আমার কফি পছন্দ না", "আমার দুধ পছন্দ"),
        ("मुझे चाय पसंद", "मुझे चाय पसंद नहीं", "दूध पसंद"),
        ("காபி விருப்பம்", "காபி விருப்பம் இல்லை", "பால் விருப்பம்"),
        ("కాఫీ ఇష్టం", "కాఫీ ఇష్టం లేదు", "పాలు ఇష్టం"),
        ("കാപ്പി ഇഷ്ടം", "കാപ്പി ഇഷ്ടം അല്ല", "പാൽ ഇഷ്ടം"),
        ("I prefer tea", "I don’t prefer tea", "I prefer milk"),
    ],
)
def test_memory_review_uses_whole_words_for_preferences(manager, positive, negative, unrelated):
    for content in (positive, negative, unrelated):
        manager.add_memory(content, memory_type="preference", approved=True)

    pairs = {
        (candidate.kind, frozenset((candidate.first.content, candidate.second.content)))
        for candidate in manager.review_candidates()
    }
    assert pairs == {("possible_conflict", frozenset((positive, negative)))}


def test_deleting_memory_removes_linked_derived_episodic_record(manager):
    record = manager.add_memory("Temporary derived note", approved=True)
    with manager.database.connect() as connection:
        with connection:
            connection.execute(
                """INSERT INTO episodic_memories
                (event_id,event_time,summary,application,outcome,memory_id)
                VALUES(?,?,?,?,?,?)""",
                (
                    "linked-event",
                    datetime.now(timezone.utc).isoformat(),
                    "Derived summary",
                    "SHU",
                    "Stored",
                    record.memory_id,
                ),
            )

    assert manager.delete_memory(record.memory_id, approved=True)
    with manager.database.connect() as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM episodic_memories WHERE event_id='linked-event'"
        ).fetchone()[0]
    assert remaining == 0
