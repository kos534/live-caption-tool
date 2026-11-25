@echo off
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install --upgrade pip || goto :fail
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt || goto :fail
.venv\Scripts\python.exe download_models.py || goto :fail
.venv\Scripts\pyinstaller.exe --noconfirm WonuvaLiveCaption.spec || goto :fail

rem Ship the pre-downloaded models next to the exe so it runs offline out of the box.
robocopy models dist\WonuvaLiveCaption\models /E /XO /NFL /NDL /NJH /NJS /NP
if errorlevel 8 goto :fail

echo.
echo Build complete: dist\WonuvaLiveCaption\WonuvaLiveCaption.exe
exit /b 0

:fail
echo.
echo Build FAILED. See errors above.
exit /b 1
