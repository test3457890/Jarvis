# One-time setup for Jarvis. Needs internet ONCE to download; after that Jarvis runs offline.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$model = "qwen3:8b"
$embed = "nomic-embed-text"
$whisper = "small.en"

Write-Host "== 1/4 Python environment" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    # Python 3.12 has the best support for the speech libraries.
    try { py -3.12 -m venv .venv } catch { python -m venv .venv }
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "== 2/4 Ollama" -ForegroundColor Cyan
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama is not installed. Get it from https://ollama.com/download then run this again." -ForegroundColor Yellow
    exit 1
}

Write-Host "== 3/4 AI models (one time: Jarvis 2.5 GB, Tuki 5.2 GB, coder 4.7 GB, memory 0.3 GB)" -ForegroundColor Cyan
ollama pull qwen3:4b
ollama pull $model
ollama pull $embed
ollama pull qwen2.5-coder:7b

Write-Host "== 4/4 Speech recognition model (one time)" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('$whisper', device='cpu', compute_type='int8'); print('whisper ready')"

Write-Host ""
& .\.venv\Scripts\python.exe -m jarvis doctor
Write-Host ""
Write-Host "Done. Double-click Jarvis.bat to start." -ForegroundColor Green
