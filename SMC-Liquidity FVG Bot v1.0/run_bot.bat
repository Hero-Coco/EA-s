@echo off
TITLE SMC-Liquidity FVG Bot v1.0
COLOR 0B

echo ======================================================================
echo           LAUNCHING SMC-LIQUIDITY FVG BOT v1.0
echo ======================================================================
echo.

:: Detect Python 3.8 executable
set PYTHON_EXE=""

if exist "%LOCALAPPDATA%\Programs\Python\Python38\python.exe" (
    set PYTHON_EXE="%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
    goto RUN
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set PYTHON_EXE=py -3.8
    goto RUN
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set PYTHON_EXE=python
    goto RUN
)

echo [ERROR] Python 3.8 was not found on your system!
echo Please ensure Python 3.8 is installed.
pause
exit /b 1

:RUN
echo Using Python: %PYTHON_EXE%
echo Starting Control Panel...
echo.
%PYTHON_EXE% bot.py

pause

