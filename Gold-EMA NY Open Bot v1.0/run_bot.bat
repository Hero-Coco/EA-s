@echo off
title Gold-EMA NY Open Bot v1.0
color 06

echo =====================================================================
echo   Starting Gold-EMA NY Open Bot v1.0 (XAUUSD M5)
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

