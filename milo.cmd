@echo off
setlocal enableextensions
REM ============================================================
REM  milo - one-command launcher for the local offline agent
REM  Ensures the LM Studio server + model are up, runs the agent
REM  against the CURRENT directory, then frees the GPU on exit.
REM
REM  Setup: put this folder on your PATH (or copy milo.cmd to a
REM  folder that is), then just run:
REM     milo
REM     milo "add unit tests to main.py"
REM
REM  Override the model with:  set MILO_MODEL=your/model-id
REM ============================================================

set "HERE=%~dp0"
set "LMS=%USERPROFILE%\.lmstudio\bin\lms.exe"
set "AGENT=%HERE%agent.py"
if "%MILO_MODEL%"=="" set "MILO_MODEL=google/gemma-4-e4b"

REM --- ensure the LM Studio server is running (idempotent) ---
"%LMS%" server start >nul 2>&1

REM --- ensure the model is loaded; only load if not already present ---
"%LMS%" ps 2>nul | findstr /C:"%MILO_MODEL%" >nul 2>&1
if errorlevel 1 (
    echo [milo] Loading %MILO_MODEL% into GPU, please wait...
    "%LMS%" load "%MILO_MODEL%" --gpu max --context-length 8192 --ttl 3600 -y >nul 2>&1
)

REM --- launch the harness in the current directory, forwarding any args ---
py "%AGENT%" --repo . --confirm %*

REM --- on exit: release the GPU (unload model) and stop the server ---
echo.
echo [milo] Releasing GPU (unloading model, stopping server)...
"%LMS%" unload --all >nul 2>&1
"%LMS%" server stop >nul 2>&1
echo [milo] GPU released. See you next time.
endlocal
