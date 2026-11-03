@echo off
title Shifted-MA Trend Master v1.0
color 0A

echo =====================================================================
echo   Starting Shifted-MA Trend Master v1.0 (Python 3.8 MT5 EA)
echo =====================================================================
echo.

if exist "C:\Users\hussa\AppData\Local\Programs\Python\Python38\python.exe" (
    "C:\Users\hussa\AppData\Local\Programs\Python\Python38\python.exe" bot.py
) else (
    py -3.8 bot.py
)

if errorlevel 1 (
    echo.
    echo [ERROR] Bot exited with an error code!
    pause
)
