[CmdletBinding()]
param(
    [switch]$Remove,
    [string]$StartupDirectory
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonwPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'

if ([string]::IsNullOrWhiteSpace($StartupDirectory)) {
    $StartupDirectory = [Environment]::GetFolderPath('Startup')
}
if ([string]::IsNullOrWhiteSpace($StartupDirectory)) {
    throw 'The current user Startup folder could not be located.'
}
$StartupDirectory = [IO.Path]::GetFullPath($StartupDirectory)
$shortcutPath = Join-Path $StartupDirectory 'SHU Assistant.lnk'
$expectedPython = [IO.Path]::GetFullPath($pythonwPath)
$expectedArguments = '-m app.cli gui'

if (-not $Remove) {
    $pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $expectedPython -PathType Leaf) -or
        -not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "SHU's virtual environment is missing. Run scripts\setup.ps1 first."
    }

    Push-Location -LiteralPath $projectRoot
    try {
        & $pythonPath -c 'from app.interface.dashboard import SHUDashboard'
        if ($LASTEXITCODE -ne 0) { throw 'Startup requires the desktop dashboard. Run scripts\setup.ps1 without -CoreOnly.' }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath $StartupDirectory -PathType Container)) {
    if ($Remove) {
        Write-Host 'No SHU startup shortcut is installed.'
        exit 0
    }
    New-Item -ItemType Directory -Path $StartupDirectory -Force | Out-Null
}

$shell = New-Object -ComObject WScript.Shell
try {
    if ($Remove) {
        if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
            Write-Host 'No SHU startup shortcut is installed.'
            exit 0
        }
        $existing = $shell.CreateShortcut($shortcutPath)
        if ([IO.Path]::GetFullPath($existing.TargetPath) -ine $expectedPython -or
            $existing.Arguments -cne $expectedArguments -or
            [IO.Path]::GetFullPath($existing.WorkingDirectory) -ine $projectRoot) {
            throw 'The shortcut name is in use by a different target; it was left untouched.'
        }
        Remove-Item -LiteralPath $shortcutPath -Force
        Write-Host 'Removed SHU from the current user Startup folder.'
        exit 0
    }

    if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
        $existing = $shell.CreateShortcut($shortcutPath)
        if ([IO.Path]::GetFullPath($existing.TargetPath) -ine $expectedPython -or
            $existing.Arguments -cne $expectedArguments -or
            [IO.Path]::GetFullPath($existing.WorkingDirectory) -ine $projectRoot) {
            throw 'The shortcut name is in use by a different target; it was left untouched.'
        }
    }

    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $expectedPython
    $shortcut.Arguments = $expectedArguments
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = 'Start the SHU desktop assistant after sign-in.'
    $shortcut.Save()
    Write-Host 'Added SHU to the current user Startup folder:' $shortcutPath
} finally {
    [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
}
