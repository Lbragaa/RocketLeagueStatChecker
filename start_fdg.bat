@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
if exist "%~dp0.venv\python.exe" goto portable
py -3 -m fdg %*
goto finished
:portable
"%~dp0.venv\python.exe" -m fdg %*
:finished
if errorlevel 1 pause
