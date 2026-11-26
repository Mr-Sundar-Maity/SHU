"""Build a private source bundle without local secrets or user data."""

from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath


ROOT_FILES = (
    ".env.example",
    ".gitignore",
    "README.md",
    "pytest.ini",
    "requirements.txt",
    "requirements-v1.txt",
)
ROOT_DIRECTORIES = ("app", "database", "memory", "scripts", "tests")
DOC_FILES = ("THIRD_PARTY_LICENSES.csv",)
REQUIRED_SETUP_FILES = {
    ".env.example",
    "requirements.txt",
    "requirements-v1.txt",
    "scripts/install.ps1",
    "scripts/setup.ps1",
    "scripts/secure-data.ps1",
    "scripts/verify.ps1",
    "app/cli.py",
    "app/config.py",
    "app/interface/dashboard.py",
    "database/database.py",
}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "backups",
    "cache",
    "credentials",
    "dist",
    "exports",
    "logs",
    "models",
    "private_data",
    "tmp",
    "user_data",
}
EXCLUDED_SUFFIXES = {
    ".db",
    ".key",
    ".onnx",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}


def _is_private_or_generated(relative_path: PurePosixPath) -> bool:
    parts = [part.casefold() for part in relative_path.parts]
    filename = parts[-1]
    if any(part in EXCLUDED_PARTS for part in parts):
        return True
    if filename == ".env" or (filename.startswith(".env.") and filename != ".env.example"):
        return True
    if Path(filename).suffix.casefold() in EXCLUDED_SUFFIXES:
        return True
    if filename in {"gmail_oauth_client.json", "client_secrets.json", "credentials.json"}:
        return True
    if "client_secret" in filename or "access_token" in filename:
        return True
    return False


def collect_files(root: Path) -> list[tuple[Path, PurePosixPath]]:
    """Collect only source allowlist paths and reject included symlinks."""
    root = root.resolve(strict=True)
    selected: set[PurePosixPath] = set()
    for name in ROOT_FILES:
        candidate = root / name
        if candidate.exists():
            if candidate.is_symlink():
                raise ValueError(f"Refusing a symlink in the package allowlist: {name}")
            if candidate.is_file():
                selected.add(PurePosixPath(name))

    for name in DOC_FILES:
        candidate = root / "docs" / name
        if candidate.exists():
            if candidate.is_symlink():
                raise ValueError(f"Refusing a symlink in the package allowlist: docs/{name}")
            if candidate.is_file():
                selected.add(PurePosixPath("docs") / name)

    for directory_name in ROOT_DIRECTORIES:
        directory = root / directory_name
        if not directory.exists():
            continue
        if directory.is_symlink():
            raise ValueError(f"Refusing a symlink in the package allowlist: {directory_name}")
        for candidate in directory.rglob("*"):
            relative = PurePosixPath(candidate.relative_to(root).as_posix())
            if _is_private_or_generated(relative):
                continue
            if candidate.is_symlink():
                raise ValueError(f"Refusing a symlink in the package allowlist: {relative}")
            if candidate.is_file():
                selected.add(relative)

    for relative in tuple(selected):
        if _is_private_or_generated(relative):
            selected.remove(relative)
    return [(root.joinpath(*relative.parts), relative) for relative in sorted(selected)]


def _check_setup_files(paths: set[str]) -> None:
    missing = sorted(REQUIRED_SETUP_FILES - paths)
    if missing:
        raise ValueError("Missing required setup files: " + ", ".join(missing))


def verify_archive(archive_path: Path, expected_paths: set[str]) -> None:
    """Check the archive listing, path safety, CRCs, and Python syntax."""
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("The source bundle contains duplicate paths")
        for name in names:
            relative = PurePosixPath(name)
            windows_relative = PureWindowsPath(name)
            if (
                relative.is_absolute()
                or windows_relative.drive
                or "\\" in name
                or ".." in relative.parts
                or ".." in windows_relative.parts
                or _is_private_or_generated(relative)
            ):
                raise ValueError("The source bundle contains a private or unsafe path")
        archive_paths = set(names)
        _check_setup_files(archive_paths)
        if archive_paths != expected_paths:
            raise ValueError("The source bundle listing differs from the allowlist")
        if archive.testzip() is not None:
            raise ValueError("The source bundle failed its CRC check")
        for name in names:
            relative = PurePosixPath(name)
            if relative.suffix.casefold() == ".py":
                compile(archive.read(name).decode("utf-8-sig"), name, "exec")


def build_bundle(root: Path, output_path: Path | None = None) -> tuple[Path, str]:
    root = root.resolve(strict=True)
    files = collect_files(root)
    expected_paths = {relative.as_posix() for _source, relative in files}
    _check_setup_files(expected_paths)
    output_path = output_path or root / "dist" / "SHU_personal_source.zip"
    output_path = output_path.resolve()
    try:
        output_path.relative_to(root / "dist")
    except ValueError as error:
        raise ValueError("The package output must be inside the project dist directory") from error
    if output_path.suffix.casefold() != ".zip":
        raise ValueError("The package output must have a .zip suffix")
    checksum_path = output_path.with_suffix(output_path.suffix + ".sha256")
    if output_path.exists() or checksum_path.exists():
        raise FileExistsError("Refusing to overwrite an existing personal bundle")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_created = False
    checksum_created = False
    try:
        with output_path.open("xb") as output_stream:
            output_created = True
            with zipfile.ZipFile(
                output_stream,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                for source, relative in files:
                    archive.write(source, arcname=relative.as_posix())
        verify_archive(output_path, expected_paths)
        digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
        with checksum_path.open("x", encoding="ascii", newline="\n") as checksum:
            checksum_created = True
            checksum.write(f"{digest}  {output_path.name}\n")
    except Exception:
        if output_created and output_path.is_file():
            output_path.unlink()
        if checksum_created and checksum_path.is_file():
            checksum_path.unlink()
        raise
    return output_path, digest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and verify a private SHU source bundle without local data."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional ZIP path inside C:\\SHU\\dist; existing files are never overwritten",
    )
    args = parser.parse_args()
    try:
        output, digest = build_bundle(Path(__file__).resolve().parents[1], args.output)
    except Exception as error:
        print("Personal source bundle was not created:", type(error).__name__, str(error))
        return 1
    print("Personal source bundle:", output)
    print("SHA-256:", digest)
    print("The archive passed path, private-file, CRC and Python syntax checks.")
    print("This ZIP has a checksum, not an Authenticode signature.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
