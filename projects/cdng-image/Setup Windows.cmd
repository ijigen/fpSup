@echo off
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Setup complete. Run CDNG Image.cmd to start.
pause
exit /b 0
:fail
echo Setup failed. Install 64-bit Python 3.12 or newer from python.org and retry.
pause
exit /b 1
