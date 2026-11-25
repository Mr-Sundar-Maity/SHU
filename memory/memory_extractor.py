"""Conservative memory-candidate extraction; never writes automatically."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    content: str
    memory_type: str = "long_term"
    source: str = "explicit_user_request"
    requires_approval: bool = True


_EXPLICIT_REMEMBER = re.compile(
    r"^\s*(?:please\s+)?remember\s+(?:that\s+)?(.+?)\s*[.!?]*\s*$",
    re.IGNORECASE,
)


class MemoryExtractor:
    """Extract only an explicit remember request for user review."""

    def extract_candidate(self, text: str) -> MemoryCandidate | None:
        match = _EXPLICIT_REMEMBER.match(text or "")
        if not match:
            return None
        content = match.group(1).strip()
        if not content:
            return None
        return MemoryCandidate(content=content)
