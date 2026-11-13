@echo off
setlocal
"%~dp0venv\Scripts\python.exe" "%~dp0run_frib.py" start %*
set "frib_result=%ERRORLEVEL%"
if not "%frib_result%"=="0" pause
exit /b %frib_result%
