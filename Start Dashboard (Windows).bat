@echo off
rem Double-click to start the Economic Machine Monitor on Windows.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run_local.py
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3 is needed and was not found.
    echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and double-click this file again.
  ) else (
    python run_local.py
  )
)
echo.
pause
