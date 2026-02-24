#!/bin/bash
# AI Transcriptor - Start Script for macOS/Linux
# by Shivam Kole

echo "============================================================"
echo "  AI Transcriptor by Shivam Kole"
echo "  Starting application..."
echo "============================================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not found. Please install Python 3.10+"
    echo "macOS: brew install python3"
    echo "Linux: sudo apt install python3 python3-pip"
    exit 1
fi

# Check dependencies
python3 -c "import fastapi" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "[INFO] Installing dependencies..."
    pip3 install -r requirements.txt --quiet
fi

echo "[OK] Starting AI Transcriptor on http://127.0.0.1:8765"
echo ""
python3 main.py
