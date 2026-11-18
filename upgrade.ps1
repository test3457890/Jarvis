# Close Jarvis first. Supply the checksum published alongside the release ZIP.
# Only shipped program files are replaced. Settings, data and credentials in %APPDATA%\Jarvis,
# the .venv folder, models and files that are not in the release manifest are left alone.
param(
    [string] $Package,
    [string] $Checksum,
    [string] $Restore
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backupRoot = Join-Path $env:APPDATA 'Jarvis\Program Backups'

function Safe-Relative([string] $Name) {
    if ([IO.Path]::IsPathRooted($Name) -or $Name -match '(^|[\\/])\.\.([\\/]|$)' -or $Name -match ':' -or $Name -notmatch '^[a-zA-Z0-9_./ -]+$') {
        throw 'Invalid package file path.'
    }
    return $Name
}

function Restore-Source([string] $Folder) {
    $state = Get-Content -LiteralPath (Join-Path $Folder 'state.json') -Raw | ConvertFrom-Json
    foreach ($entry in $state) {
        $relative = Safe-Relative $entry.name
        $destination = Join-Path $root $relative
        if ($entry.existed) {
            New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $Folder $relative) -Destination $destination -Force
        } elseif (Test-Path -LiteralPath $destination) {
            Remove-Item -LiteralPath $destination -Force
        }
    }
}

$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.ExecutablePath -eq (Join-Path $root '.venv\Scripts\python.exe') -and $_.CommandLine -match '-m\s+jarvis'
}
if ($running) { throw 'Close Jarvis before updating or restoring program files.' }
if ($Restore) {
    $selected = [IO.Path]::GetFullPath($Restore)
    $allowed = [IO.Path]::GetFullPath($backupRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $selected.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Select a backup from Jarvis Program Backups.' }
    Restore-Source $selected
    Write-Host 'Previous program files restored. Run .\.venv\Scripts\python.exe -m jarvis doctor before continuing.'
    exit 0
}
if (-not $Package -or $Checksum -notmatch '^[0-9a-fA-F]{64}$') { throw 'Provide -Package and its published -Checksum SHA256 value.' }
if ((Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash -ne $Checksum) { throw 'Package checksum does not match.' }
$stage = Join-Path ([IO.Path]::GetTempPath()) ('Jarvis Update ' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
$backup = Join-Path $backupRoot ([Guid]::NewGuid().ToString('N'))
try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $Package))
    try {
        $total = 0L
        foreach ($entry in $archive.Entries) {
            $relative = Safe-Relative $entry.FullName
            if (-not $relative.StartsWith('Jarvis/') -or $entry.Length -gt 10000000) { throw 'Invalid release package.' }
            $total += $entry.Length
            if ($total -gt 50000000) { throw 'Release package exceeds the extraction limit.' }
            $target = Join-Path $stage $relative
            New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target)
        }
    } finally { $archive.Dispose() }
    $source = Join-Path $stage 'Jarvis'
    $manifest = Get-Content -LiteralPath (Join-Path $source 'release-manifest.json') -Raw | ConvertFrom-Json
    $entries = @($manifest.files.PSObject.Properties)
    if (-not $entries.Count -or -not ($entries.Name -contains 'jarvis/__main__.py')) { throw 'Release manifest is incomplete.' }
    foreach ($entry in $entries) {
        $relative = Safe-Relative $entry.Name
        if ((Get-FileHash -LiteralPath (Join-Path $source $relative) -Algorithm SHA256).Hash -ne $entry.Value) { throw 'Release file checksum does not match.' }
    }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    $state = @()
    foreach ($entry in $entries) {
        $relative = $entry.Name
        $current = Join-Path $root $relative
        $existed = Test-Path -LiteralPath $current -PathType Leaf
        $state += [PSCustomObject]@{name=$relative; existed=$existed}
        if ($existed) {
            $saved = Join-Path $backup $relative
            New-Item -ItemType Directory -Path (Split-Path $saved) -Force | Out-Null
            Copy-Item -LiteralPath $current -Destination $saved
        }
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'state.json') -Encoding UTF8
    try {
        foreach ($entry in $entries) {
            $target = Join-Path $root $entry.Name
            New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $source $entry.Name) -Destination $target -Force
        }
    } catch {
        Restore-Source $backup
        throw
    }
    Write-Host "Updated source to $($manifest.version). Program backup saved at $backup"
    Write-Host 'Your settings and data were not changed.'
    Write-Host 'Run install.ps1 to refresh Python packages and the Start menu shortcut, then .\.venv\Scripts\python.exe -m jarvis doctor.'
    if (Test-Path -LiteralPath (Join-Path $root 'Jarvis.bat')) {
        Write-Host 'Jarvis.bat from an earlier version was left in place. It is no longer needed. Use the Start menu shortcut instead.'
    }
} finally { Remove-Item -LiteralPath $stage -Recurse -Force }
