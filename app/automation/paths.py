"""Filesystem allowlist enforcing resolved paths under approved roots."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable


class PathPolicy:
    def __init__(self, allowed_roots: Iterable[str | Path]) -> None:
        self.allowed_roots = tuple(Path(root).expanduser().resolve() for root in allowed_roots)
        if not self.allowed_roots:
            raise ValueError("At least one allowed root is required")

    def resolve(self, path: str | Path, *, must_exist: bool = False) -> Path:
        candidate = Path(path).expanduser().resolve(strict=must_exist)
        if not any(candidate == root or root in candidate.parents for root in self.allowed_roots):
            raise PermissionError("Path is outside SHU's allowed directories")
        return candidate

    def validate_filename(self, filename: str) -> str:
        if not filename or filename in {".", ".."}:
            raise ValueError("A filename is required")
        if Path(filename).name != filename or any(char in filename for char in '<>:"/\\|?*'):
            raise ValueError("Only a plain filename is allowed")
        return filename
