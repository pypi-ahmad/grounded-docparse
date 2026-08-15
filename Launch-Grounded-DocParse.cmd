@echo off
setlocal EnableExtensions
title Grounded DocParse
cd /d "%~dp0"

echo Checking Grounded DocParse setup...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-GroundedDocParse.ps1" -EnsureHost -InstallRoot "%~dp0"
if errorlevel 1 goto :failed

for %%K in (OPENAI_API_KEY OPENAI_BASE_URL GOOGLE_API_KEY OLLAMA_BASE_URL) do (
  for /f "usebackq delims=" %%V in (`powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('%%K','User')"`) do set "%%K=%%V"
)
set "DOCPARSE_WINDOWS_ROOT=%CD%"
set "DOCPARSE_OLD_WSLENV=%WSLENV%"
if defined WSLENV (
  set "WSLENV=%WSLENV%:OPENAI_API_KEY:OPENAI_BASE_URL:GOOGLE_API_KEY:OLLAMA_BASE_URL:DOCPARSE_WINDOWS_ROOT/p"
) else (
  set "WSLENV=OPENAI_API_KEY:OPENAI_BASE_URL:GOOGLE_API_KEY:OLLAMA_BASE_URL:DOCPARSE_WINDOWS_ROOT/p"
)

wsl.exe -d Ubuntu-24.04 -- bash -lc "cd \"$DOCPARSE_WINDOWS_ROOT\" && bash scripts/wsl/check-installation.sh" >nul 2>&1
if errorlevel 1 (
  echo Setup is missing or stale. Installing dependencies and model assets...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-GroundedDocParse.ps1" -Provision -NoAppLaunch -WarmEngine paddleocr-vl-1.6 -InstallRoot "%~dp0"
  if errorlevel 1 goto :restore_failed
)

wsl.exe -d Ubuntu-24.04 -- bash -lc "exec \"$DOCPARSE_WINDOWS_ROOT/scripts/wsl/launch-stack.sh\""
set "DOCPARSE_EXIT=%ERRORLEVEL%"
set "WSLENV=%DOCPARSE_OLD_WSLENV%"
if not "%DOCPARSE_EXIT%"=="0" goto :failed
start "" "http://localhost:8600"
exit /b 0

:restore_failed
set "WSLENV=%DOCPARSE_OLD_WSLENV%"
:failed
echo.
echo Startup failed. Review %%LOCALAPPDATA%%\GroundedDocParse\logs\install.log and .runtime logs.
pause
exit /b 1
