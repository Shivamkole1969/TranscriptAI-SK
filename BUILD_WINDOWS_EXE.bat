@echo off
title AI Transcriptor - Build Windows EXE
echo ============================================================
echo   AI Transcriptor - Windows EXE Builder
echo   by Shivam Kole
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from python.org
    pause
    exit /b 1
)

echo [1/4] Installing dependencies...
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet

echo [2/4] Cleaning previous build...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build

echo [3/4] Building EXE with PyInstaller...
pyinstaller ^
    --name "AI Transcriptor" ^
    --onedir ^
    --noconsole ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "custom_bundle.pem;." ^
    --hidden-import "uvicorn" ^
    --hidden-import "uvicorn.logging" ^
    --hidden-import "uvicorn.loops" ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.protocols" ^
    --hidden-import "uvicorn.protocols.http" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.protocols.websockets" ^
    --hidden-import "uvicorn.protocols.websockets.auto" ^
    --hidden-import "uvicorn.lifespan" ^
    --hidden-import "uvicorn.lifespan.on" ^
    --hidden-import "fastapi" ^
    --hidden-import "starlette" ^
    --hidden-import "jinja2" ^
    --hidden-import "httpx" ^
    --hidden-import "groq" ^
    --hidden-import "pydub" ^
    --hidden-import "fpdf" ^
    --hidden-import "yt_dlp" ^
    --hidden-import "pytubefix" ^
    --hidden-import "aiofiles" ^
    --hidden-import "multipart" ^
    --hidden-import "websockets" ^
    --icon "icon.ico" ^
    main.py

echo [4/4] Copying additional files...
if exist "ffmpeg.exe" copy /y "ffmpeg.exe" "dist\AI Transcriptor\"
if exist "custom_bundle.pem" copy /y "custom_bundle.pem" "dist\AI Transcriptor\"

echo.
echo ============================================================
echo   BUILD COMPLETE!
echo   Output: dist\AI Transcriptor\
echo   Run: dist\AI Transcriptor\AI Transcriptor.exe
echo ============================================================
pause
