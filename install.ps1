# One-time setup for Jarvis: Python environment, packages and a Start menu shortcut.
# Models are chosen and downloaded by the setup wizard that opens on first launch.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File install.ps1
# Existing settings in %APPDATA%\Jarvis are never removed by this script.
param(
    # Optional. Saves a performance profile while keeping your personal settings.
    [Alias("Profile")]
    [ValidateSet("standard", "low-memory")]
    [string] $MemoryProfile,
    # Also download the profile's Ollama and speech models here instead of in the wizard.
    [switch] $DownloadModels,
    # Skip the Start menu and folder shortcuts.
    [switch] $NoShortcut,
    # Also put a shortcut on the desktop.
    [switch] $DesktopShortcut,
    # Test hook: create the environment without installing packages.
    [switch] $SkipPackages
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$root = $PSScriptRoot

function Invoke-SetupCommand {
    param([string] $Executable, [string[]] $Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE. Fix the error above and run install.ps1 again. Completed steps are kept."
    }
}

if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Install Python 3.12 from python.org, enable Add Python to PATH, then run install.ps1 again.'
}

Write-Host "== 1/3 Python environment" -ForegroundColor Cyan
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    # Python 3.12 has the best support for the speech libraries.
    $created = $false
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $prevPref = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try { & py -3.12 -c "import sys" 2>$null | Out-Null } catch {}
        $py312Exit = $LASTEXITCODE
        $ErrorActionPreference = $prevPref
        if ($py312Exit -eq 0) {
            Invoke-SetupCommand py @("-3.12", "-m", "venv", ".venv")
            $created = $true
        }
    }
    if (-not $created) { Invoke-SetupCommand python @("-m", "venv", ".venv") }
}
if (-not $SkipPackages) {
    Invoke-SetupCommand $venvPython @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-SetupCommand $venvPython @("-m", "pip", "install", "-r", "requirements.txt")
}

if ($PSBoundParameters.ContainsKey("MemoryProfile")) {
    # apply_profile only changes model and memory settings. Everything else is preserved.
    Invoke-SetupCommand $venvPython @("-c", "from jarvis import config; config.save(config.apply_profile(config.load(), '$MemoryProfile'))")
}

Write-Host "== 2/3 Shortcuts" -ForegroundColor Cyan
if ($NoShortcut) {
    Write-Host "Skipped. Start Jarvis with: & `"$venvPython`" -m jarvis"
} else {
    # The shortcut starts Python directly. There is no batch file or extra launcher program.
    $shell = New-Object -ComObject WScript.Shell
    $places = @(
        (Join-Path $root "Start Jarvis.lnk"),
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Jarvis.lnk")
    )
    if ($DesktopShortcut) { $places += (Join-Path ([Environment]::GetFolderPath("Desktop")) "Jarvis.lnk") }
    foreach ($place in $places) {
        New-Item -ItemType Directory -Path (Split-Path $place) -Force | Out-Null
        $link = $shell.CreateShortcut($place)
        $link.TargetPath = $venvPython
        $link.Arguments = "-m jarvis"
        $link.WorkingDirectory = $root
        $link.Description = "Start the Jarvis assistant"
        $link.Save()
        Write-Host "Created $place"
    }
}

Write-Host "== 3/3 Models" -ForegroundColor Cyan
if ($DownloadModels) {
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        throw "Ollama is not installed. Get it from https://ollama.com/download then run this again."
    }
    $selected = if ($MemoryProfile) { $MemoryProfile } else { "standard" }
    # Ollama keeps partial downloads, so running this again resumes them.
    $code = "from jarvis import config, setupwizard as w; c=config.load(); t=w.start(c, {'profile': '$selected'}); t.join(); s=w.load_state(); print(s.get('error') or 'Models ready'); raise SystemExit(1 if s.get('error') else 0)"
    Invoke-SetupCommand $venvPython @("-c", $code)
} else {
    Write-Host "The setup wizard opens on first launch to choose and download models."
    Write-Host "It shows the disk space each choice needs and can resume a failed download."
}

if (-not $SkipPackages) {
    & $venvPython -m jarvis doctor
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Diagnostics found items to finish. The setup wizard can download missing models."
    }
}
Write-Host ""
Write-Host "Done. Open Jarvis from the Start menu or the 'Start Jarvis' shortcut in this folder." -ForegroundColor Green
Write-Host "PowerShell fallback: & `"$venvPython`" -m jarvis"
exit 0
