@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0dependencies\Setup-Workspace.ps1"
set "frib_result=%ERRORLEVEL%"
if not "%frib_result%"=="0" pause
exit /b %frib_result%
