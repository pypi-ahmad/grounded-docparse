@echo off
setlocal EnableExtensions
title Grounded DocParse - WSL legacy app
cd /d "%~dp0"
set "DOCPARSE_WINDOWS_ROOT=%CD%"
set "DOCPARSE_OLD_WSLENV=%WSLENV%"
if defined WSLENV (set "WSLENV=%WSLENV%:DOCPARSE_WINDOWS_ROOT/p") else (set "WSLENV=DOCPARSE_WINDOWS_ROOT/p")
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd \"$DOCPARSE_WINDOWS_ROOT\" && exec scripts/wsl/launch-stack.sh"
set "DOCPARSE_EXIT=%ERRORLEVEL%"
set "WSLENV=%DOCPARSE_OLD_WSLENV%"
if not "%DOCPARSE_EXIT%"=="0" exit /b %DOCPARSE_EXIT%
start "" "http://localhost:9356"
exit /b 0
