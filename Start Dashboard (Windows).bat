@echo off
rem Double-click to start the Economic Machine Monitor on Windows.
rem The first time, it also puts an "Economic Dashboard" icon on the desktop: after that, use the icon.
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3 is needed and was not found.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and double-click this file again.
  echo.
  pause
  exit /b 1
)
%PY% run_local.py --make-shortcut
echo.
%PY% run_local.py
echo.
pause
