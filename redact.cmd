@echo off
rem redact on Windows: same arguments as redact.sh
setlocal
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONPATH=%HERE%;%PYTHONPATH%"
"%PY%" -m nsx26.redact %*
exit /b %ERRORLEVEL%
