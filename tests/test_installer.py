import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_core_cli_operates_without_optional_v1_imports(tmp_path):
    checkout = tmp_path / "source"
    for package in ("app", "database", "memory"):
        shutil.copytree(PROJECT_ROOT / package, checkout / package, ignore=shutil.ignore_patterns("__pycache__"))

    data_dir = tmp_path / "data"
    environment = {
        name: value for name, value in os.environ.items()
        if not name.startswith(("SHU_", "LOCAL_AI_", "GEMINI_")) and name != "PYTHONPATH"
    }
    environment["SHU_DATA_DIR"] = str(data_dir)
    command = r"""
import importlib.abc
import os
import sys
from pathlib import Path

class WithoutOptionalV1(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        package = fullname.split('.', 1)[0]
        if package in {'docx', 'openpyxl', 'pptx', 'apscheduler', 'PySide6'}:
            raise ModuleNotFoundError(name=package)

sys.meta_path.insert(0, WithoutOptionalV1())
from app.cli import main

assert main(['db', 'init']) == 0
assert main(['db', 'verify']) == 0
assert main(['languages']) == 0
source = Path(os.environ['SHU_DATA_DIR']) / 'memory' / 'exports' / 'test.txt'
source.write_text('synthetic fixture', encoding='utf-8')
assert main(['files', 'preview', str(source)]) == 0
assert main(['gui']) == 2
assert main(['reminders', 'list']) == 2
"""
    result = subprocess.run(
        [sys.executable, "-c", command], cwd=checkout, env=environment,
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Integrity: ok" in result.stdout
    assert '"sha256"' in result.stdout
    assert "The dashboard requires full setup" in result.stdout
    assert "Reminders require full setup" in result.stdout
    assert "Traceback" not in result.stderr
    assert not (checkout / ".env").exists()


def run_isolated_powershell(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    if sys.platform != "win32" or not shutil.which("powershell.exe"):
        pytest.skip("Windows PowerShell is required")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script), *arguments],
        cwd=script.parent.parent, check=False, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=25,
    )


@pytest.mark.parametrize("startup", [False, True])
def test_core_install_never_registers_desktop_shortcuts(tmp_path, startup):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    install = scripts / "install.ps1"
    shutil.copyfile(PROJECT_ROOT / "scripts" / "install.ps1", install)
    (scripts / "setup.ps1").write_text(
        "param([switch]$CoreOnly)\n"
        "if (-not $CoreOnly) { throw 'Expected core mode' }\n"
        "[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'setup.called'), 'core')\n"
        "$global:LASTEXITCODE = 0\n",
        encoding="ascii",
    )
    # There is deliberately no .venv or launcher in this fixture. A regression
    # cannot install a shortcut into the real user's folders.
    arguments = ("-CoreOnly", "-EnableStartup") if startup else ("-CoreOnly",)
    result = run_isolated_powershell(install, *arguments)

    if startup:
        assert result.returncode != 0
        assert "EnableStartup requires the desktop dashboard" in result.stderr
        assert not (scripts / "setup.called").exists()
    else:
        assert result.returncode == 0, result.stderr
        assert (scripts / "setup.called").is_file()
        assert "Desktop shortcuts were not changed" in result.stdout


def test_startup_refuses_missing_console_interpreter_before_creating_directory(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    startup_script = scripts / "manage-startup.ps1"
    shutil.copyfile(PROJECT_ROOT / "scripts" / startup_script.name, startup_script)
    launchers = tmp_path / ".venv" / "Scripts"
    launchers.mkdir(parents=True)
    (launchers / "pythonw.exe").touch()
    isolated_startup = tmp_path / "Startup"

    result = run_isolated_powershell(startup_script, "-StartupDirectory", str(isolated_startup))

    assert result.returncode != 0
    assert "virtual environment is missing" in result.stderr
    assert not isolated_startup.exists()
