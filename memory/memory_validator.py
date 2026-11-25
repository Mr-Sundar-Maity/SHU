"""Validation rules for user-approved memory records."""

from __future__ import annotations

from app.security.privacy import contains_authentication_secret
from memory.memory_config import MAX_MEMORY_CHARS, MEMORY_TYPES


class MemoryValidationError(ValueError):
    """Raised when a memory candidate violates SHU's storage rules."""


def validate_memory(
    *,
    content: str,
    memory_type: str,
    sensitivity: str,
    confidence: float,
    approved: bool,
) -> None:
    if not content or not content.strip():
        raise MemoryValidationError("Memory content cannot be empty")
    if len(content) > MAX_MEMORY_CHARS:
        raise MemoryValidationError(
            f"Memory content exceeds {MAX_MEMORY_CHARS} characters"
        )
    if memory_type not in MEMORY_TYPES:
        raise MemoryValidationError(
            "Unsupported memory type: " + memory_type
        )
    if not 0.0 <= confidence <= 1.0:
        raise MemoryValidationError("Confidence must be between 0 and 1")
    if contains_authentication_secret(content):
        raise MemoryValidationError(
            "Authentication secrets cannot be stored in SHU memory"
        )
    if sensitivity.lower() in {"secret", "credential", "authentication"}:
        raise MemoryValidationError(
            "Sensitive authentication data cannot be stored in SHU memory"
        )
    if not approved:
        raise MemoryValidationError(
            "Memory must be explicitly approved before it is stored"
        )
