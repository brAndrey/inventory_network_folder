@echo off
rem ============================================================
rem  run_monitor.bat
rem
rem  Запуск main.py рядом с этим bat-файлом.
rem  Предназначен для Планировщика задач Windows (без pause).
rem
rem  Можно задать явный путь к Python:
rem      set MONITOR_PYTHON_EXE=C:\Python311\python.exe
rem ============================================================

setlocal enabledelayedexpansion
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
set "PYTHONUTF8=1"
set "PYFILE=%SCRIPT_DIR%main.py"

if not exist "%PYFILE%" (
    echo [ERROR] Python script not found: %PYFILE%
    exit /b 1
)

rem Явно указанный Python имеет приоритет.
if defined MONITOR_PYTHON_EXE (
    "%MONITOR_PYTHON_EXE%" "%PYFILE%" %*
    exit /b !errorlevel!
)

rem Пробуем py -3, затем python.
where py >nul 2>nul
if !errorlevel! equ 0 (
    py -3 "%PYFILE%" %*
    exit /b !errorlevel!
)

where python >nul 2>nul
if !errorlevel! equ 0 (
    python "%PYFILE%" %*
    exit /b !errorlevel!
)

echo [ERROR] Python 3 not found. Install Python, py launcher, or set MONITOR_PYTHON_EXE.
exit /b 1
