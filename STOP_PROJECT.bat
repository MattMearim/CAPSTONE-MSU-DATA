@echo off
setlocal
title FRIB - Stop workspace
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\Stop-Workspace.ps1"
set "frib_result=%ERRORLEVEL%"
if not "%frib_result%"=="0" pause
exit /b %frib_result%
