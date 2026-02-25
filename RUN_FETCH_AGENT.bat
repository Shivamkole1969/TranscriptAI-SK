@echo off
echo ==============================================
echo 🚀 AI Transcriptor - Local Fetch Agent Auto-Setup
echo ==============================================
echo.
echo Installing requirements...
python -m pip install yt-dlp requests --quiet
echo Starting Fetch Agent...
echo.
python local_fetch_agent.py
pause
