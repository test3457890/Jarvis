# One-time setup for Jarvis. Needs internet ONCE to download; after that Jarvis runs offline.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File install.ps1
param(
    [ValidateSet("standard", "low-memory")]
    [string] $Profile = "standard"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$model = "qwen3:8b"
$embed = "nomic-embed-text"
$whisper = "small.en"
$coder = "qwen2.5-coder:7b"
if ($Profile -eq "low-memory") {
    $model = "qwen3:4b"
    $coder = "qwen2.5-coder:1.5b"
    $whisper = "base.en"
}

function Invoke-SetupCommand {
    param([string] $Executable, [string[]] $Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE. Fix the error above and run install.ps1 again."
    }
}

Write-Host "== 1/4 Python environment" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    # Python 3.12 has the best support for the speech libraries.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Invoke-SetupCommand py @("-3.12", "-m", "venv", ".venv")
        } else {
            Invoke-SetupCommand python @("-m", "venv", ".venv")
        }
    } else {
        Invoke-SetupCommand python @("-m", "venv", ".venv")
    }
}
$venvPython = ".\.venv\Scripts\python.exe"
Invoke-SetupCommand $venvPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-SetupCommand $venvPython @("-m", "pip", "install", "-r", "requirements.txt")

Write-Host "== 2/4 Ollama" -ForegroundColor Cyan
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama is not installed. Get it from https://ollama.com/download then run this again." -ForegroundColor Yellow
    exit 1
}

Invoke-SetupCommand ollama @("list")
Write-Host "== 3/4 AI models for $Profile" -ForegroundColor Cyan
$models = @("qwen3:4b", $model, $coder)
if ($Profile -eq "standard") { $models += $embed }
foreach ($tag in ($models | Select-Object -Unique)) {
    Invoke-SetupCommand ollama @("pull", $tag)
}

Write-Host "== 4/4 Speech recognition model (one time)" -ForegroundColor Cyan
Invoke-SetupCommand $venvPython @("-c", "from faster_whisper import WhisperModel; WhisperModel('$whisper', device='cpu', compute_type='int8'); print('whisper ready')")

Invoke-SetupCommand $venvPython @("-c", "from jarvis import config; config.save(config.apply_profile(config.load(), '$Profile'))")
Write-Host ""
& $venvPython -m jarvis doctor
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Installation finished with diagnostic warnings. Review the output above."
}
Write-Host ""
Write-Host "Done. Double-click Jarvis.bat to start." -ForegroundColor Green
