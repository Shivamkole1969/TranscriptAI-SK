#!/bin/bash
echo "=============================================="
echo "🚀 AI Transcriptor - Local Fetch Agent Auto-Setup"
echo "=============================================="
echo ""
echo "Installing requirements..."
python3 -m pip install yt-dlp requests --quiet
echo "Starting Fetch Agent..."
echo ""
python3 local_fetch_agent.py
read -p "Press Enter to exit..."
