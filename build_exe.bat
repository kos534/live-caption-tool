@echo off
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
.venv\Scripts\pyinstaller.exe --noconfirm LiveCaption.spec
echo.
echo Build complete: dist\LiveCaption\LiveCaption.exe
