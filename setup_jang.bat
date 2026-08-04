@echo off
setlocal

cd /d "%~dp0"
set "PAUSE_ON_ERROR=1"
if /i "%~1"=="--no-pause" set "PAUSE_ON_ERROR=0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        if "%PAUSE_ON_ERROR%"=="1" pause
        exit /b 1
    )
)

echo Installing or updating JJZero Audio dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    if "%PAUSE_ON_ERROR%"=="1" pause
    exit /b 1
)

echo JJZero Audio setup is complete.
if "%PAUSE_ON_ERROR%"=="1" pause

endlocal
