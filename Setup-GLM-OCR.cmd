@echo off
setlocal EnableExtensions
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-GroundedDocParse.ps1" -Provision -InstallRoot "%~dp0"
exit /b %ERRORLEVEL%
