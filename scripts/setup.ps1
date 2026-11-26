[CmdletBinding()]
param(
    [switch]$CoreOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Python Launcher is required. Install Python 3.11, then run setup again.'
    }
    Push-Location -LiteralPath $projectRoot
    try {
        & py -3.11 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python 3.11 virtual environment.' }
    } finally {
        Pop-Location
    }
}

$envPath = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    $templateBytes = [IO.File]::ReadAllBytes((Join-Path $projectRoot '.env.example'))
    $stagedPath = Join-Path $projectRoot ('.env.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $stream = [IO.File]::Open($stagedPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        try {
            $stream.Write($templateBytes, 0, $templateBytes.Length)
            $stream.Flush($true)
        } finally {
            $stream.Dispose()
        }
        try {
            # Move publishes the complete template and refuses to replace a late configuration.
            [IO.File]::Move($stagedPath, $envPath)
            Write-Warning 'Created .env from the template. Review settings and add provider credentials only if needed.'
        } catch [IO.IOException] {
            $errorCode = $_.Exception.GetBaseException().HResult -band 0xffff
            if ($errorCode -notin @(80, 183) -or -not [IO.File]::Exists($envPath)) {
                throw
            }
        }
    } finally {
        [IO.File]::Delete($stagedPath)
    }
}

Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Core dependency installation failed.' }

    if (-not $CoreOnly) {
        & $pythonPath -m pip install -r requirements-v1.txt
        if ($LASTEXITCODE -ne 0) { throw 'Full v1 dependency installation failed.' }

        & $pythonPath -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Playwright Chromium installation failed.' }
    }

    & $pythonPath -m app.cli db init
    if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }

    & $pythonPath -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Installed packages have dependency conflicts.' }

    if (-not $CoreOnly) {
        & $pythonPath -c 'from app.interface.dashboard import SHUDashboard'
        if ($LASTEXITCODE -ne 0) { throw 'The dashboard could not load. Complete full setup before creating shortcuts.' }
    }

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    if ($principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        & (Join-Path $projectRoot 'scripts\secure-data.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Private SHU data ACL hardening failed.' }
    } else {
        Write-Warning 'Run scripts\secure-data.ps1 from an elevated PowerShell session to restrict .env and SHU data access.'
    }
} finally {
    Pop-Location
}

Write-Host 'SHU setup finished.'
if ($CoreOnly) {
    Write-Host 'Start with: .\.venv\Scripts\python.exe -m app.cli chat'
} else {
    Write-Host 'Start with: .\.venv\Scripts\python.exe -m app.cli gui'
}
