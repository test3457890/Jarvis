# Read-only Microsoft Defender diagnostic for a downloaded Jarvis folder or ZIP.
# It does not change Defender settings, add exclusions or remove download markers.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\check_defender.ps1 -Path "C:\Downloads\Jarvis1.2.0.zip"
param([Parameter(Mandatory = $true)][string] $Path)
$ErrorActionPreference = 'Stop'
$target = (Resolve-Path -LiteralPath $Path).Path
$files = if ((Get-Item -LiteralPath $target).PSIsContainer) {
    Get-ChildItem -LiteralPath $target -Recurse -File | Where-Object { $_.FullName -notmatch '\\\.venv\\' }
} else { @(Get-Item -LiteralPath $target) }

Write-Host "== Download marker (Mark of the Web)" -ForegroundColor Cyan
foreach ($file in $files) {
    $zone = Get-Content -LiteralPath $file.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue
    if ($zone) { Write-Host "$($file.FullName): $(($zone | Select-String 'ZoneId').Line)" }
}

Write-Host "== Recent Defender detections for these files" -ForegroundColor Cyan
$detections = Get-MpThreatDetection -ErrorAction SilentlyContinue | Where-Object {
    $resources = $_.Resources -join ' '
    $resources -like "*$target*"
}
if ($detections) {
    foreach ($detection in $detections) {
        $threat = Get-MpThreat -ThreatID $detection.ThreatID -ErrorAction SilentlyContinue
        Write-Host "$($threat.ThreatName) at $($detection.InitialDetectionTime): $($detection.Resources -join ', ')"
    }
} else { Write-Host "No recorded detections for $target." }

Write-Host "== On-demand scan of each file" -ForegroundColor Cyan
$scanner = Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe'
if (-not (Test-Path -LiteralPath $scanner)) { Write-Host 'MpCmdRun.exe was not found. Skipping scans.'; exit 0 }
foreach ($file in $files) {
    $output = & $scanner -Scan -ScanType 3 -File $file.FullName -DisableRemediation 2>&1
    $status = if ($LASTEXITCODE -eq 0) { 'no threat found' } else { 'FLAGGED: ' + (($output | Select-String 'Threat').Line -join '; ') }
    Write-Host "$($file.Name): $status"
}
Write-Host 'Report any flagged file name and threat name in a GitHub issue. Do not disable Defender.'
