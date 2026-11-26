@echo off
rem Builds Wonuva Live Caption for distribution:
rem   1. dist\WonuvaLiveCaption\WonuvaLiveCaption.exe   (PyInstaller; signed if configured)
rem   2. dist\installer\WonuvaLiveCaptionSetup-<version>.exe   (Inno Setup; signed if configured)
rem
rem The installer doesn't include the speech models; the app downloads them on first run.
rem   build_exe.bat offline   also copies the models into dist\WonuvaLiveCaption\models, for a
rem                           portable folder that works without internet (zip it yourself).
rem   build_exe.bat nosignin  builds an app that doesn't ask for a Wonuva sign-in (until the
rem                           Wonuva sign-in endpoints are live). Options can be combined.
rem
rem Signing: see sign.bat (set the variables, e.g. by calling your own signing-env.bat first).
rem Installer: needs Inno Setup 6 (https://jrsoftware.org/isdl.php); skipped if not installed.

cd /d "%~dp0"
set "OFFLINE="
set "NOSIGNIN="
:args
if "%~1"=="" goto :args_done
if /i "%~1"=="offline" set "OFFLINE=1"
if /i "%~1"=="nosignin" set "NOSIGNIN=1"
shift
goto :args
:args_done

if not exist .venv (
    python -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install --upgrade pip || goto :fail
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt || goto :fail

for /f "delims=" %%v in ('.venv\Scripts\python.exe -c "import config; print(config.APP_VERSION)"') do set "VERSION=%%v"
if not defined VERSION goto :fail
echo Building Wonuva Live Caption %VERSION%

rem build_info.py is read by config.py (REQUIRE_SIGN_IN); rewritten on every build.
if defined NOSIGNIN (
    echo Sign-in: NOT required in this build
    (echo REQUIRE_SIGN_IN = False)> build_info.py
) else (
    (echo REQUIRE_SIGN_IN = True)> build_info.py
)
.venv\Scripts\pyinstaller.exe --noconfirm WonuvaLiveCaption.spec || goto :fail
call "%~dp0sign.bat" dist\WonuvaLiveCaption\WonuvaLiveCaption.exe || goto :fail

if defined OFFLINE (
    .venv\Scripts\python.exe download_models.py --to dist\WonuvaLiveCaption\models || goto :fail
)

rem ---- installer ------------------------------------------------------------------------
set "ISCC="
for /f "delims=" %%i in ('where ISCC.exe 2^>nul') do set "ISCC=%%i"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo.
    echo Inno Setup not found: installer skipped. Install Inno Setup 6 to build it.
    goto :done
)

set "SIGN_ARGS="
if defined AZURE_SIGNING_METADATA set "SIGN_ARGS=1"
if defined SIGN_PFX set "SIGN_ARGS=1"
if defined SIGN_ARGS (
    "%ISCC%" /Q /DAppVersion=%VERSION% /DSIGN "/Swonuva=cmd.exe /c call $q%CD%\sign.bat$q $f" installer\WonuvaLiveCaption.iss || goto :fail
) else (
    "%ISCC%" /Q /DAppVersion=%VERSION% installer\WonuvaLiveCaption.iss || goto :fail
)
echo Installer: dist\installer\WonuvaLiveCaptionSetup-%VERSION%.exe

:done
echo.
echo Build complete: dist\WonuvaLiveCaption\WonuvaLiveCaption.exe
exit /b 0

:fail
echo.
echo Build FAILED. See errors above.
exit /b 1
