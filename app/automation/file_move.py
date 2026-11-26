"""Move a reviewed file on Windows without replacing an existing path."""

from __future__ import annotations

import hashlib
import sys
from contextlib import ExitStack
from pathlib import Path


def move_reviewed_file(
    source: Path, destination: Path, root: Path, sha256: str, *, max_bytes: int,
) -> int:
    """Hash and rename the same locked file object, then verify its new path."""
    if sys.platform != "win32":
        raise OSError("Verified file moves require Windows")

    try:
        import pywintypes
        import win32con
        import win32file
    except ImportError as error:
        raise OSError("Verified file moves require the full SHU Windows setup") from error

    def opened_path(handle) -> Path:
        # The normalized DOS file name uses the extended path prefix.
        return Path(win32file.GetFinalPathNameByHandle(handle, 0).removeprefix("\\\\?\\"))

    def checked_open(stack: ExitStack, path: Path, *, directory: bool):
        if directory:
            access = win32con.GENERIC_READ
            flags = win32file.FILE_FLAG_BACKUP_SEMANTICS
            # Windows opens the parent for writing when renaming an entry.
            # Continue to block deletion or renaming of the parent itself.
            share = win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE
        else:
            access = win32con.GENERIC_READ | win32con.DELETE
            flags = 0
            share = win32con.FILE_SHARE_READ
        # Require the approved entry itself and deny other writers and renames.
        handle = win32file.CreateFile(
            str(path), access, share, None, win32con.OPEN_EXISTING,
            flags | win32file.FILE_FLAG_OPEN_REPARSE_POINT, None,
        )
        stack.callback(handle.Close)
        attributes = win32file.GetFileInformationByHandle(handle)[0]
        if (
            attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT
            or bool(attributes & win32con.FILE_ATTRIBUTE_DIRECTORY) != directory
            or opened_path(handle) != path
        ):
            raise PermissionError("An approved path changed or is not a regular file or directory")
        return handle

    def fingerprint(handle) -> tuple[int, str]:
        size = win32file.GetFileSize(handle)
        if size > max_bytes:
            raise ValueError("Verified file moves are limited to 64 MiB")
        digest = hashlib.sha256()
        win32file.SetFilePointer(handle, 0, win32file.FILE_BEGIN)
        remaining = size
        while remaining:
            status, chunk = win32file.ReadFile(handle, min(remaining, 1024 * 1024))
            if status or not chunk:
                raise OSError("Could not read all the reviewed bytes")
            digest.update(chunk)
            remaining -= len(chunk)
        return size, digest.hexdigest()

    if len(root.drive) != 2 or root.drive[1] != ":":
        raise PermissionError("Use an approved directory on a local Windows drive")
    parents = {root}
    for item in (source, destination):
        parents.update(parent for parent in item.parents if parent.is_relative_to(root))

    renamed = False
    try:
        with ExitStack() as handles:
            # Hold every approved directory in the two paths until verification.
            for parent in sorted(parents, key=lambda path: (len(path.parts), str(path))):
                checked_open(handles, parent, directory=True)
            handle = checked_open(handles, source, directory=False)
            before = fingerprint(handle)
            if before[1] != sha256:
                raise ValueError("The source changed since preview. Review it again before moving.")
            win32file.SetFileInformationByHandle(handle, win32file.FileRenameInfo, {
                "ReplaceIfExists": False, "RootDirectory": 0, "FileName": str(destination),
            })
            renamed = True
            if opened_path(handle) != destination or source.exists() or fingerprint(handle) != before:
                raise OSError("Could not verify the completed move")
            return before[0]
    except (OSError, ValueError, pywintypes.error) as error:
        if renamed:
            raise OSError("Windows renamed the file, but the result was not verified. Inspect both paths.") from error
        if isinstance(error, pywintypes.error):
            if error.winerror in {80, 183}:  # ERROR_FILE_EXISTS, ERROR_ALREADY_EXISTS
                raise FileExistsError("The destination already exists") from error
            raise OSError(f"Windows refused the file move (error {error.winerror})") from error
        raise
