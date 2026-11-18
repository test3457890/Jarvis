# One-time setup for Jarvis. Needs internet ONCE to download; after that Jarvis runs offline.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$model = "qwen3:8b"
$embed = "nomic-embed-text"
$whisper = "small.en"

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

Write-Host "== 3/4 AI models (one time: Jarvis 2.5 GB, Tuki 5.2 GB, coder 4.7 GB, memory 0.3 GB)" -ForegroundColor Cyan
foreach ($tag in @("qwen3:4b", $model, $embed, "qwen2.5-coder:7b")) {
    Invoke-SetupCommand ollama @("pull", $tag)
}

Write-Host "== 4/4 Speech recognition model (one time)" -ForegroundColor Cyan
Invoke-SetupCommand $venvPython @("-c", "from faster_whisper import WhisperModel; WhisperModel('$whisper', device='cpu', compute_type='int8'); print('whisper ready')")

Write-Host ""
& $venvPython -m jarvis doctor
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Installation finished with diagnostic warnings. Review the output above."
}
Write-Host ""
Write-Host "Done. Double-click Jarvis.bat to start." -ForegroundColor Green
