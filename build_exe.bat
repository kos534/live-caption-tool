@echo off
REM Build Live Caption to a single exe. Requires: pip install -r requirements.txt -r requirements-build.txt
setlocal
cd /d "%~dp0"

echo Checking PyInstaller...
python -c "import PyInstaller" 2>nul || (
    echo Installing PyInstaller...
    python -m pip install -r requirements-build.txt
)

echo Checking sounddevice (required for build)...
python -c "import sounddevice" 2>nul || (
    echo Installing run dependencies...
    python -m pip install -r requirements.txt
)

echo Cleaning previous build (close any running LiveCaption or PyInstaller if "in use")...
if exist build rmdir /s /q build 2>nul
if exist dist rmdir /s /q dist 2>nul

echo Building exe (one file, no console)...
python -m PyInstaller --noconfirm live-caption.spec

if %ERRORLEVEL% equ 0 (
    echo.
    echo Done. Run: dist\LiveCaption\LiveCaption.exe
    echo Put your Vosk model in a "models" folder next to LiveCaption.exe.
    echo Config will be saved as live-caption-config.json next to the exe.
) else (
    echo Build failed.
    exit /b 1
)
