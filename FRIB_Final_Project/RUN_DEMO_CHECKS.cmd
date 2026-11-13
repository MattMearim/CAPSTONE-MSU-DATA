@echo off
setlocal
call "%~dp0FRIB_Decision_Support\Start FRIB.cmd" --test-lab --manifest "%~dp0Live_Demo_Data\configuration\test_lab\manifest.json" --output "%~dp0Demo_Check_Results"
set "FRIB_EXIT=%ERRORLEVEL%"
if "%FRIB_EXIT%"=="0" echo All live-demo checks passed. Read Demo_Check_Results\TEST_LAB_RESULTS.md.
if not "%FRIB_EXIT%"=="0" echo Checks did not finish successfully. Read the explanation above.
pause
exit /b %FRIB_EXIT%
