"""User-controlled memory storage, retrieval, correction and deletion."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from database.database import Database
from database.models import MemoryRecord
from memory.memory_config import DEFAULT_CONFIDENCE
from memory.memory_validator import validate_memory

_UNSET = object()
_REVIEW_NEGATIONS = {
    "not", "no", "never", "don't", "doesn't", "isn't", "cannot", "can't",
    "nahi", "nahin", "nahiin", "mat", "nahi", "না", "নয়", "নয়", "নেই",
    "இல்லை", "அல்ல", "కాదు", "లేదు", "नहीं", "नही", "मत", "അല്ല", "ഇല്ല",
}
_REVIEW_PREFERENCE_WORDS = {
    "prefer", "prefers", "preferred", "preference", "favorite", "favourite",
    "like", "likes", "liked", "love", "loves", "enjoy", "enjoys",
    "পছন্দ", "পছন্দের", "पसंद", "पसंदीदा", "விருப்பம்", "ఇష్టం", "ഇഷ്ടം",
}
_REVIEW_STOP_WORDS = {
    "i", "me", "my", "we", "our", "you", "your", "the", "a", "an", "is",
    "are", "am", "was", "were", "be", "to", "of", "for", "in", "on", "and",
    "that", "this", "it", "আমি", "আমার", "হয়", "হয়", "है", "मैं", "मेरा",
}
_MEMORY_QUERY_STOP_WORDS = {
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "is", "are", "am", "was", "were", "be", "do", "does", "did", "can",
    "could", "would", "should", "will", "shall", "may", "might", "must",
    "i", "me", "my", "mine", "we", "our", "you", "your", "yours", "they",
    "them", "their", "theirs", "he", "him", "his", "she", "her", "hers",
    "it", "its", "the", "a", "an", "to", "of", "for", "in", "on", "at",
    "and", "or", "about", "please", "tell", "use", "remember", "আমার", "আমি",
    "আমাকে", "আমাদের", "তুমি", "তোমার", "আপনি", "আপনার", "আপনাকে", "কি", "কী",
    "কোন", "কোনটি", "বলুন", "বলো", "হবে", "হয়", "হয়", "আছে", "করতে",
    "मेरा", "मेरी", "मेरे", "मैं", "मुझे", "क्या", "कौन", "बताओ", "बताइए",
    "है", "हैं", "हूँ", "हूं", "चाहिए", "எனது", "என்", "என்ன", "எது", "எந்த",
    "நான்", "எனக்கு", "சொல்லு", "சொல்லுங்கள்", "வேண்டும்", "నా", "నాది", "నేను",
    "నాకు", "ఏమిటి", "ఏది", "ఏ", "చెప్పు", "చెప్పండి", "ఉంది", "ఉన్నది", "కావాలి",
    "എന്റെ", "ഞാൻ", "എനിക്ക്", "എന്ത്", "എന്താണ്", "ഏത്", "പറയൂ", "പറയുക",
    "ആണ്", "ആണോ", "വേണം",
}


@dataclass(frozen=True, slots=True)
class MemoryReviewCandidate:
    """Read-only heuristic match; SHU never merges or deletes it automatically."""

    kind: str
    first: MemoryRecord
    second: MemoryRecord
    reason: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        memory_id=row["memory_id"],
        memory_type=row["type"],
        content=row["content"],
        source=row["source"],
        sensitivity=row["sensitivity"],
        confidence=float(row["confidence"]),
        approved=bool(row["approved"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        retention_until=row["retention_until"],
    )


class MemoryManager:
    """Store approved memories in SQLite with provenance and audit events."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def add_memory(
        self,
        content: str,
        *,
        memory_type: str = "long_term",
        source: str = "user",
        sensitivity: str = "normal",
        confidence: float = DEFAULT_CONFIDENCE,
        approved: bool = False,
        retention_until: str | datetime | None = None,
    ) -> MemoryRecord:
        validate_memory(
            content=content,
            memory_type=memory_type,
            sensitivity=sensitivity,
            confidence=confidence,
            approved=approved,
        )
        memory_id = str(uuid.uuid4())
        timestamp = _now()
        retention = _normalize_retention(retention_until)
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    """INSERT INTO memories
                    (memory_id,type,content,source,sensitivity,confidence,approved,created_at,updated_at,retention_until)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        memory_id,
                        memory_type,
                        content.strip(),
                        source,
                        sensitivity,
                        confidence,
                        1,
                        timestamp,
                        timestamp,
                        retention,
                    ),
                )
                self._audit(connection, memory_id, "memory.create", "success")
        return self.get_memory(memory_id)

    def get_memory(self, memory_id: str) -> MemoryRecord:
        now = _now()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id = ? AND approved = 1 "
                "AND (retention_until IS NULL OR julianday(retention_until) > julianday(?))",
                (memory_id, now),
            ).fetchone()
        if row is None:
            raise KeyError("Approved memory not found")
        return _record(row)

    def list_memories(self, *, memory_type: str | None = None) -> list[MemoryRecord]:
        query = (
            "SELECT * FROM memories WHERE approved = 1 "
            "AND (retention_until IS NULL OR julianday(retention_until) > julianday(?))"
        )
        parameters: list[str] = [_now()]
        if memory_type is not None:
            query += " AND type = ?"
            parameters.append(memory_type)
        query += " ORDER BY updated_at DESC, memory_id"
        with self.database.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_record(row) for row in rows]

    def search(self, query: str, *, limit: int = 10) -> list[MemoryRecord]:
        terms = _memory_query_terms(query)[:20]
        if not terms:
            return []
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        score = " + ".join(
            "CASE WHEN content LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END"
            for _ in terms
        )
        where = " OR ".join("content LIKE ? ESCAPE '\\'" for _ in terms)
        values = tuple("%" + _escape_like(term) + "%" for term in terms)
        now = _now()
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT *, ({score}) AS relevance FROM memories WHERE approved = 1 "
                f"AND (retention_until IS NULL OR julianday(retention_until) > julianday(?)) "
                f"AND ({where}) ORDER BY relevance DESC, confidence DESC, updated_at DESC LIMIT ?",
                (*values, now, *values, limit),
            ).fetchall()
        return [_record(row) for row in rows]

    def review_candidates(
        self, *, max_memories: int = 500, limit: int = 100
    ) -> list[MemoryReviewCandidate]:
        """Find likely duplicate or conflicting pairs for a human to review.

        This is a lexical review aid, not a semantic contradiction detector. It
        performs no writes and intentionally errs toward showing uncertain pairs.
        """
        if not 1 <= max_memories <= 2_000:
            raise ValueError("max_memories must be between 1 and 2000")
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        now = _now()
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE approved=1 "
                "AND (retention_until IS NULL OR julianday(retention_until) > julianday(?)) "
                "ORDER BY updated_at DESC, memory_id LIMIT ?",
                (now, max_memories),
            ).fetchall()
        records = [_record(row) for row in rows]
        results: list[MemoryReviewCandidate] = []
        generic_words = (
            _REVIEW_NEGATIONS
            | _REVIEW_STOP_WORDS
            | _REVIEW_PREFERENCE_WORDS
        )
        for index, first in enumerate(records):
            first_words = _review_words(first.content)
            first_normalized = " ".join(first_words)
            for second in records[index + 1 :]:
                second_words = _review_words(second.content)
                second_normalized = " ".join(second_words)
                if first_normalized and first_normalized == second_normalized:
                    results.append(
                        MemoryReviewCandidate(
                            "duplicate", first, second,
                            "Same words after case, punctuation and Unicode normalization.",
                        )
                    )
                else:
                    first_content = set(first_words) - generic_words
                    second_content = set(second_words) - generic_words
                    shared = first_content & second_content
                    polarity_differs = bool(set(first_words) & _REVIEW_NEGATIONS) != bool(
                        set(second_words) & _REVIEW_NEGATIONS
                    )
                    preference_pair = first.memory_type == second.memory_type == "preference"
                    different_values = bool(first_content - shared) and bool(
                        second_content - shared
                    )
                    possible_conflict = (
                        bool(shared)
                        and preference_pair
                        and (polarity_differs or different_values)
                    ) or (polarity_differs and len(shared) >= 2)
                    if possible_conflict:
                        results.append(
                            MemoryReviewCandidate(
                                "possible_conflict", first, second,
                                "Overlapping terms with opposite wording or differing preference values; compare manually.",
                            )
                        )
                if len(results) >= limit:
                    return results
        return results

    def update_memory(
        self,
        memory_id: str,
        content: str,
        *,
        approved: bool = False,
        confidence: float | None = None,
        sensitivity: str | None = None,
        retention_until: str | datetime | None | object = _UNSET,
    ) -> MemoryRecord:
        current = self.get_memory(memory_id)
        new_confidence = current.confidence if confidence is None else confidence
        new_sensitivity = current.sensitivity if sensitivity is None else sensitivity
        validate_memory(
            content=content,
            memory_type=current.memory_type,
            sensitivity=new_sensitivity,
            confidence=new_confidence,
            approved=approved,
        )
        retention = (
            current.retention_until
            if retention_until is _UNSET
            else _normalize_retention(retention_until)
        )
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    "UPDATE memories SET content=?, sensitivity=?, confidence=?, updated_at=?, retention_until=? WHERE memory_id=?",
                    (content.strip(), new_sensitivity, new_confidence, _now(), retention, memory_id),
                )
                self._audit(connection, memory_id, "memory.update", "success")
        return self.get_memory(memory_id)

    def purge_expired_memories(self, *, approved: bool = False) -> int:
        """Delete records past their explicitly configured retention date."""
        if not approved:
            raise PermissionError("Purging expired memories requires explicit approval")
        now = _now()
        with self.database.connect() as connection:
            with connection:
                rows = connection.execute(
                    "SELECT memory_id FROM memories WHERE retention_until IS NOT NULL "
                    "AND julianday(retention_until) <= julianday(?)",
                    (now,),
                ).fetchall()
                for row in rows:
                    connection.execute(
                        "DELETE FROM episodic_memories WHERE memory_id=?",
                        (row["memory_id"],),
                    )
                    self._audit(connection, row["memory_id"], "memory.retention_expire", "success")
                if rows:
                    connection.executemany(
                        "DELETE FROM memories WHERE memory_id=?",
                        [(row["memory_id"],) for row in rows],
                    )
        return len(rows)

    def delete_memory(self, memory_id: str, *, approved: bool = False) -> bool:
        if not approved:
            raise PermissionError("Deleting a memory requires explicit approval")
        with self.database.connect() as connection:
            with connection:
                exists = connection.execute(
                    "SELECT 1 FROM memories WHERE memory_id=?", (memory_id,)
                ).fetchone()
                if exists is None:
                    return False
                connection.execute(
                    "DELETE FROM episodic_memories WHERE memory_id=?", (memory_id,)
                )
                self._audit(connection, memory_id, "memory.delete", "success")
                connection.execute("DELETE FROM memories WHERE memory_id=?", (memory_id,))
        return True

    def export_approved_memories(self, *, approved: bool = False) -> Path:
        """Export approved memory records to the private data-directory exports folder."""
        if not approved:
            raise PermissionError("Exporting personal memory requires explicit approval")
        export_dir = self.database.path.parent / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc)
        filename = timestamp.strftime("memories-%Y%m%dT%H%M%S%fZ.json")
        destination = export_dir / filename
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE approved=1 "
                "AND (retention_until IS NULL OR julianday(retention_until) > julianday(?)) "
                "ORDER BY created_at,memory_id",
                (_now(),),
            ).fetchall()
        payload = {
            "exported_at": _now(),
            "memories": [
                {
                    "memory_id": row["memory_id"],
                    "type": row["type"],
                    "content": row["content"],
                    "source": row["source"],
                    "sensitivity": row["sensitivity"],
                    "confidence": row["confidence"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "retention_until": row["retention_until"],
                }
                for row in rows
            ],
        }
        try:
            with destination.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return destination

    @staticmethod
    def _audit(connection: sqlite3.Connection, memory_id: str, action: str, result: str) -> None:
        connection.execute(
            """INSERT INTO audit_logs
            (log_id,actor,action_summary,risk,approval,result,timestamp)
            VALUES (?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                "memory_manager",
                json.dumps({"memory_id": memory_id, "action": action}),
                "L2",
                "approved",
                result,
                _now(),
            ),
        )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _memory_query_terms(query: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", query).casefold()
    words: list[str] = []
    current: list[str] = []
    for character in normalized:
        if unicodedata.category(character)[0] in {"L", "M", "N"}:
            current.append(character)
        elif current:
            words.append("".join(current))
            current.clear()
    if current:
        words.append("".join(current))
    return list(dict.fromkeys(
        word for word in words if word not in _MEMORY_QUERY_STOP_WORDS
    ))


def _review_words(content: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", content).casefold()
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)?", normalized, flags=re.UNICODE)


def _normalize_retention(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("retention_until must be an ISO-8601 timestamp") from error
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("retention_until must include a timezone")
    normalized = value.astimezone(timezone.utc)
    if normalized <= datetime.now(timezone.utc):
        raise ValueError("retention_until must be in the future")
    return normalized.isoformat(timespec="microseconds")
