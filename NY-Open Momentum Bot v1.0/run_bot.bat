@echo off
title NY-Open Momentum Bot v1.0
color 0A

echo =======================================================================
echo          NY-Open Momentum Bot v1.0 (NAS100 M15 / M5 EA)
echo =======================================================================
echo.

:: Detect Python executable
if exist "%LOCALAPPDATA%\Programs\Python\Python38\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set PYTHON_CMD=python
    ) else (
        set PYTHON_CMD=py -3.8
    )
)

echo Checking dependencies from requirements.txt...
%PYTHON_CMD% -m pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Failed to auto-install dependencies. Please ensure pip is accessible.
)

echo.
echo Launching NY-Open Momentum Bot v1.0 Control Panel...
echo.
%PYTHON_CMD% bot.py

echo.
echo Bot execution terminated.
pause

