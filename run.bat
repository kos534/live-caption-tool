@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

start "" pythonw main.py
echo Live Caption started. You can close this window.
timeout /t 2 >nul
