@echo off
rem Code-sign one file:  sign.bat path\to\file.exe
rem
rem Configure ONE of these (as environment variables, e.g. in a local signing-env.bat you don't
rem commit) and build_exe.bat signs the app exe, the installer and its uninstaller:
rem
rem   Azure Trusted Signing (recommended):
rem     AZURE_SIGNING_DLIB      full path to Azure.CodeSigning.Dlib.dll
rem                             (from the Microsoft.Trusted.Signing.Client NuGet package, bin\x64)
rem     AZURE_SIGNING_METADATA  full path to a metadata.json like installer\signing-metadata.example.json
rem     Sign in first with "az login" (or set AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_CLIENT_SECRET).
rem
rem   Certificate file (.pfx, e.g. an OV certificate):
rem     SIGN_PFX                full path to the .pfx
rem     SIGN_PFX_PASSWORD       its password
rem
rem   Optional: SIGNTOOL = full path to signtool.exe (otherwise the newest Windows SDK one is used).
rem
rem Exits 0 without signing when nothing is configured, so unsigned test builds still work.

setlocal
if "%~1"=="" (
    echo usage: sign.bat FILE
    exit /b 2
)
if not defined AZURE_SIGNING_METADATA if not defined SIGN_PFX (
    echo [sign] Signing not configured: %~nx1 left unsigned.
    exit /b 0
)

set "ST=%SIGNTOOL%"
if not defined ST (
    for /f "delims=" %%i in ('where /r "%ProgramFiles(x86)%\Windows Kits\10\bin" signtool.exe 2^>nul ^| findstr /i "\\x64\\"') do set "ST=%%i"
)
if not defined ST (
    echo [sign] signtool.exe not found. Install the Windows SDK "Signing Tools" or set SIGNTOOL.
    exit /b 1
)

if defined AZURE_SIGNING_METADATA (
    "%ST%" sign /v /fd SHA256 /tr http://timestamp.acs.microsoft.com /td SHA256 /dlib "%AZURE_SIGNING_DLIB%" /dmdf "%AZURE_SIGNING_METADATA%" "%~1"
) else (
    "%ST%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f "%SIGN_PFX%" /p "%SIGN_PFX_PASSWORD%" "%~1"
)
if errorlevel 1 (
    echo [sign] FAILED to sign %~nx1
    exit /b 1
)
echo [sign] Signed %~nx1
exit /b 0
