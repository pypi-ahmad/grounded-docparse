@echo off
setlocal EnableExtensions
title GLM-OCR Setup
cd /d "%~dp0"

where wsl.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: wsl.exe is not available on this machine.
  echo Install WSL manually: https://learn.microsoft.com/windows/wsl/install
  goto :failed
)

echo Checking for the Ubuntu-24.04 WSL distro...
wsl.exe -d Ubuntu-24.04 -- true >nul 2>&1
if errorlevel 1 (
  net session >nul 2>&1
  if errorlevel 1 (
    echo Administrator privileges are required to install the Ubuntu-24.04 WSL distro.
    echo Requesting elevation; approve the prompt in the new window...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    exit /b
  )
  echo Ubuntu-24.04 not found under WSL. Installing...
  wsl.exe --install -d Ubuntu-24.04
  echo.
  echo First-time WSL setup may require a restart, and the first launch of
  echo Ubuntu-24.04 will ask you to create a UNIX username and password.
  echo Finish that, then re-run Setup-GLM-OCR.cmd.
  goto :failed
)

echo Checking GPU passthrough inside WSL...
wsl.exe -d Ubuntu-24.04 -- nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo ERROR: nvidia-smi failed inside WSL.
  echo Install the NVIDIA CUDA-enabled driver for WSL on Windows:
  echo https://developer.nvidia.com/cuda/wsl
  echo Then re-run this file.
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
  set "WSLENV=%WSLENV%:OPENAI_API_KEY:OPENAI_BASE_URL:DOCPARSE_WINDOWS_ROOT/p"
) else (
  set "WSLENV=OPENAI_API_KEY:OPENAI_BASE_URL:DOCPARSE_WINDOWS_ROOT/p"
)

echo Setting up the GLM-OCR environment and starting the stack...
echo This downloads GLM-OCR and PP-DocLayout weights on first run.
wsl.exe -d Ubuntu-24.04 -- bash -lc "exec \"$DOCPARSE_WINDOWS_ROOT/scripts/wsl/launch-stack.sh\""
set "DOCPARSE_EXIT=%ERRORLEVEL%"
set "WSLENV=%DOCPARSE_OLD_WSLENV%"

if not "%DOCPARSE_EXIT%"=="0" goto :failed

start "" "http://localhost:8501"
echo.
echo GLM-OCR is ready. This window can be closed.
echo Future runs: use Launch-GLM-OCR.cmd, or re-run this file.
ping 127.0.0.1 -n 4 >nul
exit /b 0

:failed
echo.
echo Setup did not complete. Review .runtime\vllm.log and .runtime\streamlit.log if present.
pause
exit /b 1
