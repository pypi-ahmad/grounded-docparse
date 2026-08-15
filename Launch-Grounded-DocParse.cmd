@echo off
setlocal EnableExtensions
title Grounded DocParse
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\launch-native.ps1" -InstallRoot "%~dp0"
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo Startup failed. Review %%LOCALAPPDATA%%\GroundedDocParse\logs\native-launch.log.
pause
exit /b 1
