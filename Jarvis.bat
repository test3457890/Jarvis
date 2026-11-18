@echo off
cd /d "%~dp0"
rem Force offline mode for the speech model cache so nothing is fetched online.
set HF_HUB_OFFLINE=1
".venv\Scripts\python.exe" -m jarvis %*
pause
