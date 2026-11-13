@echo off
setlocal
call "%~dp0FRIB_Decision_Support\Start FRIB.cmd" --local-ai %*
exit /b %ERRORLEVEL%
