@echo off
setlocal
title FRIB - Start workspace
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\Start-Workspace.ps1" %*
set "frib_result=%ERRORLEVEL%"
if not "%frib_result%"=="0" (
  echo.
  echo Startup did not finish. See dependencies\logs\setup.log for details.
  pause
)
exit /b %frib_result%
