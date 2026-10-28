@echo off
setlocal
title Iris
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython

%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if errorlevel 1 goto nopython

if not exist ".venv\Scripts\python.exe" (
  echo First start: setting things up. This takes about a minute...
  %PY% -m venv .venv
  if errorlevel 1 goto fail
)
if not exist ".venv\.installed" (
  echo Installing the few packages Iris needs...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --default-timeout 90 --retries 8 -r requirements.txt
  if errorlevel 1 goto fail
  echo ok> ".venv\.installed"
)

".venv\Scripts\python.exe" app.py
echo.
echo Iris stopped. Press any key to close.
pause >nul
exit /b 0

:nopython
echo.
echo Iris needs Python 3.10 or newer, and it was not found.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then double-click "LAUNCH IRIS" again.
echo.
pause
exit /b 1

:fail
echo.
echo Setup failed. Check your internet connection and try again.
echo If it keeps failing, delete the .venv folder and run this launcher again.
echo.
pause
exit /b 1
