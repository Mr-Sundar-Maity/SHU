$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project virtual environment not found at $pythonPath. Run scripts\setup.ps1 first."
}

Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Installed packages have dependency conflicts.' }

    & $pythonPath -m compileall -q app database memory
    if ($LASTEXITCODE -ne 0) { throw 'Python compilation check failed.' }

    & $pythonPath -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'The SHU test suite failed.' }

    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw 'Node.js/npm is required for dashboard verification. Run full setup first.'
    }
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        & npm.cmd run lint
        if ($LASTEXITCODE -ne 0) { throw 'Frontend TypeScript verification failed.' }
        & npm.cmd test
        if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend production build failed.' }
    } finally { Pop-Location }

    & $pythonPath -m app.cli db verify
    if ($LASTEXITCODE -ne 0) { throw 'SQLite integrity or schema verification failed.' }

    & $pythonPath -m app.cli doctor
    if ($LASTEXITCODE -ne 0) { throw 'A core environment diagnostic failed; review the FAIL entries above.' }
} finally {
    Pop-Location
}

Write-Host 'SHU verification finished. Review WARN entries for external or hardware prerequisites.'
