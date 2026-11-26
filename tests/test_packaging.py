import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit
import zipfile

import pytest

from scripts.package_personal import REQUIRED_SETUP_FILES, build_bundle, collect_files, verify_archive


@pytest.fixture
def bootstrap_tree(tmp_path):
    root = tmp_path / "shu"
    for name in REQUIRED_SETUP_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return root


def test_readme_relative_links_are_in_personal_bundle_manifest():
    root = Path(__file__).resolve().parents[1]
    members = {relative.as_posix() for _, relative in collect_files(root)}
    readme = (root / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^()\s]+)\)", readme):
        link = urlsplit(target)
        if link.path and not link.scheme and not link.netloc:
            assert link.path in members, f"Missing linked file: {target}"


def test_personal_bundle_excludes_secrets_user_data_and_generated_files(bootstrap_tree):
    root = bootstrap_tree
    (root / "app" / "voice").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "tests").mkdir()
    (root / "credentials").mkdir()
    (root / "tmp" / "pdfs").mkdir(parents=True)
    (root / "app" / "voice" / "stt_engine.py").write_text(
        "class Engine: pass\n", encoding="utf-8"
    )
    (root / "app" / "models").mkdir()
    (root / "app" / "models" / "wake.onnx").write_bytes(b"model")
    (root / "database" / "shu.db").write_bytes(b"database")
    (root / "docs" / "STATUS.md").write_text("status", encoding="utf-8")
    (root / "docs" / "THIRD_PARTY_LICENSES.csv").write_text(
        "package,license\nshu,personal\n", encoding="utf-8"
    )
    (root / "tests" / "test_engine.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (root / ".env.example").write_text("SHU_PROVIDER=ollama\n", encoding="utf-8")
    (root / ".env").write_text("SHU_API_KEY=do-not-include\n", encoding="utf-8")
    (root / "credentials" / "gmail_oauth_client.json").write_text(
        '{"client_secret":"do-not-include"}', encoding="utf-8"
    )
    (root / "tmp" / "pdfs" / "private.pdf").write_bytes(b"user-data")

    archive_path = root / "dist" / "SHU_personal_source.zip"
    output, digest = build_bundle(root, archive_path)

    assert output == archive_path
    assert len(digest) == 64
    assert archive_path.with_suffix(".zip.sha256").read_text(encoding="ascii") == (
        f"{digest}  {archive_path.name}\n"
    )
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == digest
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "app/voice/stt_engine.py" in names
    assert "docs/THIRD_PARTY_LICENSES.csv" in names
    assert "docs/STATUS.md" not in names
    assert ".env.example" in names
    assert ".env" not in names
    assert not any("gmail_oauth_client" in name for name in names)
    assert not any(name.endswith((".db", ".onnx", ".pdf")) for name in names)

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        build_bundle(root, archive_path)
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    "unsafe_name",
    ("../outside.py", "C:/outside.py", r"folder\..\outside.py"),
)
def test_archive_verifier_rejects_unsafe_paths(tmp_path, unsafe_name):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(unsafe_name, "pass\n")

    with pytest.raises(ValueError, match="private or unsafe path"):
        verify_archive(archive_path, {unsafe_name})


def test_archive_verifier_accepts_utf8_bom_in_python_source(tmp_path):
    archive_path = tmp_path / "bom.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in REQUIRED_SETUP_FILES:
            archive.writestr(name, "")
        archive.writestr("app/module.py", "\ufeffvalue = 'ok'\n".encode("utf-8"))

    verify_archive(archive_path, REQUIRED_SETUP_FILES | {"app/module.py"})


@pytest.mark.parametrize("missing", sorted(REQUIRED_SETUP_FILES))
def test_incomplete_checkout_cannot_publish_a_bundle(bootstrap_tree, missing):
    (bootstrap_tree / missing).unlink()
    with pytest.raises(ValueError, match="Missing required setup files") as error:
        build_bundle(bootstrap_tree)
    assert missing in str(error.value)
    assert not (bootstrap_tree / "dist").exists()


def test_archive_verifier_rejects_matching_but_incomplete_inventory(tmp_path):
    archive_path = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("app/cli.py", "")
    with pytest.raises(ValueError, match="Missing required setup files"):
        verify_archive(archive_path, {"app/cli.py"})
