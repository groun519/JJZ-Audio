@echo off
setlocal

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows.ps1" %*
if errorlevel 1 (
    echo JJZero Audio build failed.
    exit /b 1
)

echo JJZero Audio build complete.
endlocal
