@echo off
setlocal EnableExtensions
title PaddleOCR-VL-1.6 Launcher
cd /d "%~dp0"

echo Starting PaddleOCR-VL-1.6...
set "DOCPARSE_START_ENGINE=paddleocr-vl-1.6"

where wsl.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: WSL is not installed or is unavailable.
  goto :failed
)

set "OPENAI_API_KEY="
for /f "usebackq delims=" %%V in (`powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','User')"`) do set "OPENAI_API_KEY=%%V"
set "OPENAI_BASE_URL="
for /f "usebackq delims=" %%V in (`powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('OPENAI_BASE_URL','User')"`) do set "OPENAI_BASE_URL=%%V"
if not defined OPENAI_API_KEY echo WARNING: OPENAI_API_KEY is not set in the Windows user environment. Luna features will be unavailable.

set "DOCPARSE_WINDOWS_ROOT=%CD%"
set "DOCPARSE_OLD_WSLENV=%WSLENV%"
if defined WSLENV (
  set "WSLENV=%WSLENV%:OPENAI_API_KEY:OPENAI_BASE_URL:DOCPARSE_WINDOWS_ROOT/p:DOCPARSE_START_ENGINE:DOCPARSE_PADDLE_VLLM_PORT:DOCPARSE_PADDLE_API_PORT"
) else (
  set "WSLENV=OPENAI_API_KEY:OPENAI_BASE_URL:DOCPARSE_WINDOWS_ROOT/p:DOCPARSE_START_ENGINE:DOCPARSE_PADDLE_VLLM_PORT:DOCPARSE_PADDLE_API_PORT"
)

wsl.exe -d Ubuntu-24.04 -- bash -lc "exec \"$DOCPARSE_WINDOWS_ROOT/scripts/wsl/launch-stack.sh\""
set "DOCPARSE_EXIT=%ERRORLEVEL%"
set "WSLENV=%DOCPARSE_OLD_WSLENV%"

if not "%DOCPARSE_EXIT%"=="0" goto :failed

start "" "http://localhost:8600"
echo.
echo PaddleOCR-VL-1.6 is ready. This window can be closed.
ping 127.0.0.1 -n 4 >nul
exit /b 0

:failed
echo.
echo Startup failed. Review .runtime\paddle-vllm.log, .runtime\paddle-api.log, and .runtime\streamlit.log.
pause
exit /b 1
