@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
set "PYTHONUTF8=1"
set "MONITOR_ENTRY_BAT=run_inventory.bat"
set "PYFILE=%SCRIPT_DIR%main.py"

set "LOG_DIR=%SCRIPT_DIR%Log"
set "BAT_LOG=%LOG_DIR%\bat.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 2>nul

call :log "=== START ==="
call :log "script: %PYFILE%"

if not exist "%PYFILE%" (
    call :log "ERROR: script not found"
    echo [ERROR] Python script not found: %PYFILE%
    echo Log file: "%BAT_LOG%"
    pause
    exit /b 1
)

if defined INVENTORY_PYTHON_EXE (
    call :log "python: %INVENTORY_PYTHON_EXE%"
    "%INVENTORY_PYTHON_EXE%" "%PYFILE%" %* >>"%BAT_LOG%" 2>&1
    set "PY_EXIT=!errorlevel!"
    call :log "exit code: !PY_EXIT!"
    echo Done. Logs: "%LOG_DIR%\monitor.log" and "%BAT_LOG%"
    exit /b !PY_EXIT!
)

where py >nul 2>nul
if !errorlevel! equ 0 (
    call :log "python: py -3"
    py -3 "%PYFILE%" %* >>"%BAT_LOG%" 2>&1
    set "PY_EXIT=!errorlevel!"
    call :log "exit code: !PY_EXIT!"
    echo Done. Logs: "%LOG_DIR%\monitor.log" and "%BAT_LOG%"
    exit /b !PY_EXIT!
)

where python >nul 2>nul
if !errorlevel! equ 0 (
    call :log "python: python"
    python "%PYFILE%" %* >>"%BAT_LOG%" 2>&1
    set "PY_EXIT=!errorlevel!"
    call :log "exit code: !PY_EXIT!"
    echo Done. Logs: "%LOG_DIR%\monitor.log" and "%BAT_LOG%"
    exit /b !PY_EXIT!
)

call :log "ERROR: Python 3 not found"
echo [ERROR] Python 3 not found. Install Python, py launcher, or set INVENTORY_PYTHON_EXE.
echo Log file: "%BAT_LOG%"
pause
exit /b 1

:log
>>"%BAT_LOG%" echo [%date% %time:~0,8%] %MONITOR_ENTRY_BAT%: %~1
goto :eof
