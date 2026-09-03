@echo off
rem ============================================================
rem  run_inventory.bat
rem
rem  Запуск main.py рядом с этим bat-файлом.
rem  Подходит для ручного запуска и планировщика задач Windows.
rem
rem  Пример:
rem      run_inventory.bat
rem      run_inventory.bat my_config.ini
rem ============================================================

chcp 65001 >nul
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PYTHONUTF8=1"
set "PYFILE=%SCRIPT_DIR%main.py"

rem При необходимости укажите полный путь к python.exe, например:
rem set "INVENTORY_PYTHON_EXE=C:\Python311\python.exe"

if not exist "%PYFILE%" (
    echo [ERROR] Python script not found: %PYFILE%
    exit /b 1
)

if defined INVENTORY_PYTHON_EXE (
    "%INVENTORY_PYTHON_EXE%" "%PYFILE%" %*
    exit /b !errorlevel!
)

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

echo [ERROR] Python 3 not found. Install Python, py launcher, or set INVENTORY_PYTHON_EXE.
pause
exit /b 1