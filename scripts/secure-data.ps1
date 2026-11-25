[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Project virtual environment is missing. Run scripts\setup.ps1 first.'
}

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator privileges are required. Open PowerShell as Administrator and run scripts\secure-data.ps1.'
}

Push-Location -LiteralPath $projectRoot
try {
    $configuredDataPath = (& $pythonPath -c "from app.config import get_settings; print(get_settings().data_dir)" | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $configuredDataPath) {
        throw 'Could not resolve SHU_DATA_DIR from the current configuration.'
    }
    $configuredOAuthPath = (& $pythonPath -c "from app.config import get_settings; p=get_settings().gmail_oauth_client_secrets; print(p.resolve() if p else '')" | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not resolve the configured Gmail OAuth client file.'
    }
} finally {
    Pop-Location
}
$dataPath = [System.IO.Path]::GetFullPath($configuredDataPath)
$volumeRoot = [System.IO.Path]::GetPathRoot($dataPath)
if ($dataPath.TrimEnd('\') -ieq $volumeRoot.TrimEnd('\')) {
    throw 'SHU_DATA_DIR cannot be a drive or share root.'
}
$dataPath = $dataPath.TrimEnd('\')
$projectPrefix = $projectRoot + '\'
if ($dataPath -eq $projectRoot -or $dataPath.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'SHU_DATA_DIR must be outside the project source folder before ACL hardening.'
}

if (-not (Test-Path -LiteralPath $dataPath)) {
    New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
}

$envPath = Join-Path $projectRoot '.env'
$targets = [System.Collections.Generic.List[System.IO.FileSystemInfo]]::new()
$dataRootItem = Get-Item -LiteralPath $dataPath -Force
if (-not $dataRootItem.PSIsContainer) {
    throw 'SHU_DATA_DIR exists but is not a directory.'
}
$targets.Add($dataRootItem)
$dataChildren = @(Get-ChildItem -LiteralPath $dataPath -Force -Recurse)
foreach ($child in $dataChildren) {
    $targets.Add($child)
}

if (Test-Path -LiteralPath $envPath) {
    $envItem = Get-Item -LiteralPath $envPath -Force
    if ($envItem.PSIsContainer) {
        throw '.env exists but is not a file.'
    }
    $targets.Add($envItem)
}
if ($configuredOAuthPath -and (Test-Path -LiteralPath $configuredOAuthPath)) {
    if (-not (Test-Path -LiteralPath $configuredOAuthPath -PathType Leaf)) {
        throw 'The configured Gmail OAuth client path is not a file.'
    }
    $oauthItem = Get-Item -LiteralPath $configuredOAuthPath -Force
    $alreadyTargeted = @($targets | Where-Object { $_.FullName -ieq $oauthItem.FullName }).Count -gt 0
    if (-not $alreadyTargeted) {
        $targets.Add($oauthItem)
    }
}

# Do not recurse through junctions or symbolic links: that could change ACLs
# outside the configured SHU data directory.
$reparsePoint = [System.IO.FileAttributes]::ReparsePoint
foreach ($target in $targets) {
    if (($target.Attributes -band $reparsePoint) -ne 0) {
        throw 'A private SHU path is a reparse point. Resolve it manually before hardening ACLs.'
    }
}

$currentSid = $identity.User
$systemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$administratorsSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$fullControl = [System.Security.AccessControl.FileSystemRights]::FullControl
$allow = [System.Security.AccessControl.AccessControlType]::Allow
$none = [System.Security.AccessControl.PropagationFlags]::None

function Set-PrivatePathAcl {
    param(
        [Parameter(Mandatory)]
        [System.IO.FileSystemInfo]$Item
    )

    $acl = Get-Acl -LiteralPath $Item.FullName
    # Remove inherited and explicit rules, then apply the same narrow allow-list
    # to every existing object. Directory rules inherit to future descendants.
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))) {
        $acl.RemoveAccessRuleSpecific($rule)
    }

    if ($Item.PSIsContainer) {
        $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else {
        $inheritance = [System.Security.AccessControl.InheritanceFlags]::None
    }

    foreach ($sid in @($currentSid, $systemSid, $administratorsSid)) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $sid, $fullControl, $inheritance, $none, $allow
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Item.FullName -AclObject $acl
}

foreach ($target in $targets) {
    Set-PrivatePathAcl -Item $target
}

$allowedSids = @($currentSid.Value, $systemSid.Value, $administratorsSid.Value)
foreach ($target in $targets) {
    $acl = Get-Acl -LiteralPath $target.FullName
    $rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
    $actualSids = @($rules | ForEach-Object { $_.IdentityReference.Value } | Sort-Object -Unique)
    $hasUnexpectedRule = @($rules | Where-Object {
        $_.AccessControlType -ne $allow -or $_.FileSystemRights -ne $fullControl
    }).Count -gt 0
    $hasAllExpected = @($allowedSids | Where-Object { $_ -notin $actualSids }).Count -eq 0
    $hasUnexpectedSid = @($actualSids | Where-Object { $_ -notin $allowedSids }).Count -gt 0
    if ($hasUnexpectedRule -or -not $hasAllExpected -or $hasUnexpectedSid) {
        throw 'ACL verification failed for a private SHU path; inspect permissions before use.'
    }
}

Write-Host 'SHU private data and .env ACLs are restricted to the current user, SYSTEM and Administrators.'
