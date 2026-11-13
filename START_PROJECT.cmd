@echo off
setlocal
if not exist "%~dp0dependencies\ai\real-ai-validation.json" (
  call "%~dp0SETUP_PROJECT.cmd"
  if errorlevel 1 exit /b 1
)
if not exist "%~dp0dependencies\venv\Scripts\python.exe" (
  call "%~dp0SETUP_PROJECT.cmd"
  if errorlevel 1 exit /b 1
)
call "%~dp0dependencies\Start FRIB.cmd" %*
exit /b %ERRORLEVEL%
