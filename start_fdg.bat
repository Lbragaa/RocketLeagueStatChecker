@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
if exist "%~dp0.venv\python.exe" (
  "%~dp0.venv\python.exe" -m fdg %*
) else (
py -3 -m fdg %*
)
if errorlevel 1 pause
