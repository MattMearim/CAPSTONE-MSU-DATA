@echo off
setlocal
set "FRIB_CONFIG_DIR=%~dp0FRIB_Decision_Support\config"
set "FRIB_DATA_DIR=%~dp0Demo_Workspace_AI"
set "FRIB_EMBEDDING_PROVIDER=sentence_transformers"
set "FRIB_EMBEDDING_MODEL=all-MiniLM-L6-v2"
set "FRIB_VECTOR_PROVIDER=sqlite"
echo Starting fictional data with real local AI in Demo_Workspace_AI.
echo Stop any previous FRIB launcher with Ctrl+C before starting this one.
call "%~dp0FRIB_Decision_Support\Start FRIB.cmd" --local-ai %*
exit /b %ERRORLEVEL%
