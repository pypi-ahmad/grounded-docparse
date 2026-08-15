@echo off
setlocal EnableExtensions
title Grounded DocParse - Setup GLM-OCR
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-GroundedDocParse.ps1" -EnsureHost -InstallRoot "%~dp0"
if errorlevel 1 goto :failed
set "DOCPARSE_WINDOWS_ROOT=%CD%"
set "DOCPARSE_OLD_WSLENV=%WSLENV%"
if defined WSLENV (set "WSLENV=%WSLENV%:DOCPARSE_WINDOWS_ROOT/p") else (set "WSLENV=DOCPARSE_WINDOWS_ROOT/p")
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd \"$DOCPARSE_WINDOWS_ROOT\" && bash scripts/wsl/check-installation.sh" >nul 2>&1
if errorlevel 1 (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-GroundedDocParse.ps1" -Provision -NoAppLaunch -WarmEngine glm-ocr -InstallRoot "%~dp0"
  if errorlevel 1 goto :restore_failed
)
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd \"$DOCPARSE_WINDOWS_ROOT\" && bash scripts/wsl/manage-ocr-stack.sh ensure glm-ocr"
if errorlevel 1 goto :restore_failed
set "WSLENV=%DOCPARSE_OLD_WSLENV%"
echo GLM-OCR is loaded, warmed, and ready on the GPU.
exit /b 0
:restore_failed
set "WSLENV=%DOCPARSE_OLD_WSLENV%"
:failed
echo GLM-OCR setup failed. Review the installer and .runtime logs.
pause
exit /b 1
