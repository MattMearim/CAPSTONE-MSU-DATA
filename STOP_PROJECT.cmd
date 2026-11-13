@echo off
setlocal
call "%~dp0dependencies\Stop FRIB.cmd"
exit /b %ERRORLEVEL%
