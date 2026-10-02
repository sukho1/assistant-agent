@echo off
rem diary-rag MCP stdio launcher (Windows).
rem Resolves every path from this script's own directory (%~dp0), so it works
rem regardless of the client's working directory and contains no absolute paths.
setlocal
set "HF_HUB_OFFLINE=1"
set "TQDM_DISABLE=1"
set "PYTHONIOENCODING=utf-8"
"%~dp0.venv\Scripts\python.exe" "%~dp0server.py" %*
exit /b %ERRORLEVEL%
