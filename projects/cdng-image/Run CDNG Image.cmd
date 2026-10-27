@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo Please run Setup Windows.cmd first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" run.py
