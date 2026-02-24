@echo off
title AI Transcriptor
echo ============================================================
echo   AI Transcriptor by Shivam Kole
echo   Starting application...
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Check dependencies
python -c "import fastapi" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing dependencies...
    pip install -r requirements.txt --quiet
)

echo [OK] Starting AI Transcriptor on http://127.0.0.1:8765
echo.
python main.py
pause
