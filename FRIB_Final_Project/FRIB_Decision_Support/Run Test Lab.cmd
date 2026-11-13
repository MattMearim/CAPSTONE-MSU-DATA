@echo off
setlocal
cd /d "%~dp0"
echo Running fictional examples in disposable storage. Your saved workspace is preserved.
call "Start FRIB.cmd" --test-lab --output "test_lab_results"
if errorlevel 1 (
  echo A check failed. See test_lab_results for its expected and observed result.
  pause
  exit /b 1
)
echo Test Lab complete. Open test_lab_results\TEST_LAB_RESULTS.md for the results.
pause

