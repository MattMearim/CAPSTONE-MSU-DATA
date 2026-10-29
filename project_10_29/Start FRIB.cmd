@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_windows.ps1" %*
set "FRIB_EXIT=%ERRORLEVEL%"
if not "%FRIB_EXIT%"=="0" (
  echo.
  echo FRIB could not start. The explanation is shown above.
  pause
)
exit /b %FRIB_EXIT%
