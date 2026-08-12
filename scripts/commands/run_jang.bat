@echo off
setlocal

for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"
set "PAUSE_ON_ERROR=1"
if /i "%~1"=="--no-pause" set "PAUSE_ON_ERROR=0"

if not exist ".venv\Scripts\python.exe" (
    echo JJZero Audio is not set up yet. Running setup...
    call "%~dp0setup_jang.bat" --no-pause
    if errorlevel 1 (
        echo JJZero Audio setup failed.
        if "%PAUSE_ON_ERROR%"=="1" pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import jang_app" >nul 2>&1
if errorlevel 1 (
    echo JJZero Audio dependencies are not installed.
    echo Run scripts\commands\setup_jang.bat and try again.
    if "%PAUSE_ON_ERROR%"=="1" pause
    exit /b 1
)

echo Starting JJZero Audio...
".venv\Scripts\python.exe" -m jang_app
if errorlevel 1 (
    echo Application exited with an error.
    if "%PAUSE_ON_ERROR%"=="1" pause
    exit /b 1
)

endlocal
