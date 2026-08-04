@echo off
setlocal

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_installer.ps1" %*
if errorlevel 1 (
    echo JJZero Audio installer build failed.
    exit /b 1
)

echo JJZero Audio installer build complete.
endlocal
