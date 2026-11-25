[CmdletBinding()]
param(
    [switch]$CoreOnly,
    [switch]$EnableStartup,
    [switch]$RemoveShortcuts
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonwPath = [IO.Path]::GetFullPath(
    (Join-Path $projectRoot '.venv\Scripts\pythonw.exe')
)
$shortcutArguments = '-m app.cli gui'
$shortcutName = 'SHU Assistant.lnk'
$programsDirectory = [Environment]::GetFolderPath('Programs')
$startupDirectory = [Environment]::GetFolderPath('Startup')

if ([string]::IsNullOrWhiteSpace($programsDirectory)) {
    throw 'The current user Start Menu folder could not be located.'
}
$startMenuDirectory = Join-Path $programsDirectory 'SHU'
$shortcutTargets = @(
    (Join-Path $startMenuDirectory $shortcutName)
)
if ($EnableStartup -or $RemoveShortcuts) {
    if ([string]::IsNullOrWhiteSpace($startupDirectory)) {
        throw 'The current user Startup folder could not be located.'
    }
    $shortcutTargets += Join-Path $startupDirectory $shortcutName
}

function Test-SHUShortcutTarget {
    param([Parameter(Mandatory)][string]$ShortcutPath)

    if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) {
        return $false
    }
    $existing = $shell.CreateShortcut($ShortcutPath)
    try {
        if ([string]::IsNullOrWhiteSpace($existing.TargetPath) -or
            [string]::IsNullOrWhiteSpace($existing.WorkingDirectory)) {
            return $false
        }
        return (
            [IO.Path]::GetFullPath($existing.TargetPath) -ieq $pythonwPath -and
            $existing.Arguments -ceq $shortcutArguments -and
            [IO.Path]::GetFullPath($existing.WorkingDirectory) -ieq $projectRoot
        )
    } finally {
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($existing) | Out-Null
    }
}

function Set-SHUShortcut {
    param([Parameter(Mandatory)][string]$ShortcutPath)

    $directory = Split-Path -Parent $ShortcutPath
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    if ((Test-Path -LiteralPath $ShortcutPath -PathType Leaf) -and
        -not (Test-SHUShortcutTarget -ShortcutPath $ShortcutPath)) {
        throw "A different shortcut already uses the SHU name; it was left untouched: $ShortcutPath"
    }

    $shortcut = $shell.CreateShortcut($ShortcutPath)
    try {
        $shortcut.TargetPath = $pythonwPath
        $shortcut.Arguments = $shortcutArguments
        $shortcut.WorkingDirectory = $projectRoot
        $shortcut.Description = 'Start the SHU desktop assistant.'
        $shortcut.Save()
    } finally {
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) | Out-Null
    }
    Write-Host 'Installed shortcut:' $ShortcutPath
}

function Remove-SHUShortcut {
    param([Parameter(Mandatory)][string]$ShortcutPath)

    if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) {
        return
    }
    if (-not (Test-SHUShortcutTarget -ShortcutPath $ShortcutPath)) {
        throw "Shortcut does not point to this SHU project; it was left untouched: $ShortcutPath"
    }
    Remove-Item -LiteralPath $ShortcutPath -Force
    Write-Host 'Removed shortcut:' $ShortcutPath
}

$shell = $null
try {
    $shell = New-Object -ComObject WScript.Shell

    if ($RemoveShortcuts) {
        if ($CoreOnly -or $EnableStartup) {
            throw 'RemoveShortcuts cannot be combined with CoreOnly or EnableStartup.'
        }
        foreach ($shortcutPath in $shortcutTargets) {
            if ((Test-Path -LiteralPath $shortcutPath -PathType Leaf) -and
                -not (Test-SHUShortcutTarget -ShortcutPath $shortcutPath)) {
                throw "A shortcut does not point to this SHU project; no shortcuts were removed: $shortcutPath"
            }
        }
        foreach ($shortcutPath in $shortcutTargets) {
            Remove-SHUShortcut -ShortcutPath $shortcutPath
        }
        Write-Host 'Shortcut removal finished. SHU files and user data were preserved.'
        return
    }

    $setupScript = Join-Path $PSScriptRoot 'setup.ps1'
    if ($CoreOnly) {
        & $setupScript -CoreOnly
    } else {
        & $setupScript
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'SHU setup failed; no shortcuts were installed.'
    }
    if (-not (Test-Path -LiteralPath $pythonwPath -PathType Leaf)) {
        throw "SHU setup finished without the expected GUI launcher: $pythonwPath"
    }

    Set-SHUShortcut -ShortcutPath $shortcutTargets[0]
    if ($EnableStartup) {
        Set-SHUShortcut -ShortcutPath $shortcutTargets[1]
    }
    Write-Host 'SHU personal installation finished.'
    if (-not $EnableStartup) {
        Write-Host 'Startup launch is off. Use -EnableStartup to add a current-user logon shortcut.'
    }
} finally {
    if ($null -ne $shell) {
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
    }
}
