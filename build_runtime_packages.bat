@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_runtime_packages.ps1" %*
if errorlevel 1 pause
