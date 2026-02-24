import os
import stat
import shutil
from pathlib import Path

# Setup paths
src_dir = Path("/Users/shivam.kole/Downloads/Transcriptor SK")
app_name = "AI Transcriptor.app"
app_dir = Path("/Users/shivam.kole/Applications") / app_name

# Refresh if exists
if app_dir.exists():
    shutil.rmtree(app_dir)

# Create layout
app_dir.mkdir(parents=True, exist_ok=True)
macos_dir = app_dir / "Contents" / "MacOS"
res_dir = app_dir / "Contents" / "Resources"
macos_dir.mkdir(parents=True, exist_ok=True)
res_dir.mkdir(parents=True, exist_ok=True)

# Copy icon
icon_src = src_dir / "icon.icns"
if icon_src.exists():
    shutil.copy(icon_src, res_dir / "icon.icns")

# Write Info.plist
info_plist = app_dir / "Contents" / "Info.plist"
info_plist.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>run</string>
    <key>CFBundleIconFile</key>
    <string>icon</string>
    <key>CFBundleName</key>
    <string>AI Transcriptor</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>''')

# Write run script (background runner snippet)
run_script = macos_dir / "run"
run_script_sh = f'''#!/bin/bash
DIR="/Users/shivam.kole/Downloads/Transcriptor SK"
cd "$DIR"

# Check if application is already running on port 8765
if lsof -Pi :8765 -sTCP:LISTEN -t >/dev/null ; then
    # It's already running, just open the browser
    open "http://127.0.0.1:8765"
else
    # Start it up and let webview handle the browser
    /opt/homebrew/bin/python3 main.py
fi
'''
run_script.write_text(run_script_sh)

# Make executable
os.chmod(run_script, run_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

print(f"✅ Mac App created successfully at: {app_dir}")
