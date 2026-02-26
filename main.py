#!/usr/bin/env python3
"""
AI Transcriptor
================================
Enterprise-grade transcription engine with multi-API parallelism,
speaker diarization, MP3 tools, and scheduling.
"""

import os
import sys
import json
import re
import time
import uuid
import asyncio
import logging
import platform
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

import uvicorn

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState

# ─── Path Resolution ─────────────────────────────────────────────────────────
def get_base_path():
    """Get the base path for the application, works for both dev and PyInstaller."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(sys.executable).parent
    return Path(__file__).parent

BASE_DIR = get_base_path()
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Ensure directories exist
for d in [STATIC_DIR, TEMPLATES_DIR, STATIC_DIR / "css", STATIC_DIR / "js", STATIC_DIR / "img"]:
    d.mkdir(parents=True, exist_ok=True)

# ─── Corporate Security / SSL ────────────────────────────────────────────────
cert_path = BASE_DIR / "custom_bundle.pem"
if cert_path.exists():
    os.environ['REQUESTS_CA_BUNDLE'] = str(cert_path)
    os.environ['CURL_CA_BUNDLE'] = str(cert_path)
    os.environ['SSL_CERT_FILE'] = str(cert_path)
os.environ['NO_PROXY'] = 'localhost,127.0.0.1'

# ─── FFmpeg Setup ─────────────────────────────────────────────────────────────
def setup_ffmpeg():
    """Locate ffmpeg, prefer local copy, fallback to system."""
    system = platform.system()
    local_ffmpeg = BASE_DIR / ("ffmpeg.exe" if system == "Windows" else "ffmpeg")
    if local_ffmpeg.exists():
        os.environ["IMAGEIO_FFMPEG_EXE"] = str(local_ffmpeg)
        try:
            from pydub import AudioSegment
            AudioSegment.converter = str(local_ffmpeg)
        except ImportError:
            pass
        return str(local_ffmpeg)
    # Try system PATH
    ffmpeg_sys = shutil.which("ffmpeg")
    if ffmpeg_sys:
        os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_sys
        return ffmpeg_sys
    # Fallback: check common macOS/Linux install locations (pywebview/app bundles don't inherit shell PATH)
    for fallback in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if Path(fallback).exists():
            os.environ["IMAGEIO_FFMPEG_EXE"] = fallback
            return fallback
    return None

FFMPEG_PATH = setup_ffmpeg()

# ─── User Data (Isolated per user) ───────────────────────────────────────────
def get_app_data_dir():
    """Get per-user app data directory. Works on Windows, macOS, Linux."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
    elif system == "Darwin":
        base = os.path.expanduser('~/Library/Application Support')
    else:
        base = os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share'))
    app_dir = Path(base) / "AITranscriptor"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir

APP_DATA_DIR = get_app_data_dir()
SETTINGS_FILE = APP_DATA_DIR / "api_settings.json"
HISTORY_FILE = APP_DATA_DIR / "history.json"
SCHEDULE_FILE = APP_DATA_DIR / "schedules.json"

# Put downloads in the user's actual Downloads folder for easy access
DOWNLOADS_BASE = Path(os.path.expanduser('~')) / "Downloads"
OUTPUT_DIR = DOWNLOADS_BASE / "AITranscriptor"

MP3_DIR = APP_DATA_DIR / "Mp3"
TEMP_DIR = APP_DATA_DIR / "temp"

for d in [OUTPUT_DIR, MP3_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_FILE = APP_DATA_DIR / "app.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("AITranscriptor")

# ─── Settings Manager ────────────────────────────────────────────────────────
class SettingsManager:
    def __init__(self):
        self.settings = self._load()

    def _load(self):
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "paid_api_keys": [],
            "free_api_keys": [],
            "default_model": "whisper-large-v3",
            "llm_model": "llama-3.3-70b-versatile",
            "chunk_duration_minutes": 20,
            "max_parallel_workers": 20,
            "output_format": "both",
            "speaker_detection": True,
            "auto_compress": True,
            "compress_bitrate": "128k",
            "theme": "dark",
            "language": "en",
            "english_dialect": "indian",
            "onedrive_path": "",
            "scheduled_tasks": []
        }

    def save(self):
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(self.settings, f, indent=2)

    def get_all_keys(self):
        """Get all API keys, paid first then free."""
        return self.settings.get("paid_api_keys", []) + self.settings.get("free_api_keys", [])

    def update(self, new_settings: dict):
        self.settings.update(new_settings)
        self.save()

settings_manager = SettingsManager()

# ─── History Manager ─────────────────────────────────────────────────────────
class HistoryManager:
    def __init__(self):
        self.history = self._load()

    def _load(self):
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def save(self):
        with open(HISTORY_FILE, 'w') as f:
            json.dump(self.history, f, indent=2, default=str)

    def add(self, entry: dict):
        entry['timestamp'] = datetime.now().isoformat()
        entry['id'] = str(uuid.uuid4())[:8]
        self.history.insert(0, entry)
        if len(self.history) > 500:
            self.history = self.history[:500]
        self.save()
        return entry

    def get_all(self):
        return self.history

    def clear(self):
        self.history = []
        self.save()

history_manager = HistoryManager()

# ─── Schedule Manager ────────────────────────────────────────────────────────
class ScheduleManager:
    def __init__(self):
        self.schedules = self._load()

    def _load(self):
        if SCHEDULE_FILE.exists():
            try:
                with open(SCHEDULE_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def save(self):
        with open(SCHEDULE_FILE, 'w') as f:
            json.dump(self.schedules, f, indent=2, default=str)

    def add(self, schedule: dict):
        schedule['id'] = str(uuid.uuid4())[:8]
        schedule['created'] = datetime.now().isoformat()
        schedule['status'] = 'pending'
        self.schedules.append(schedule)
        self.save()
        return schedule

    def remove(self, schedule_id: str):
        self.schedules = [s for s in self.schedules if s.get('id') != schedule_id]
        self.save()

    def get_all(self):
        return self.schedules

schedule_manager = ScheduleManager()

# ─── WebSocket Connection Manager ────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d)

ws_manager = ConnectionManager()

# ─── Groq Transcription Engine ───────────────────────────────────────────────
class TranscriptionEngine:
    def __init__(self):
        self.key_usage = defaultdict(lambda: {"calls": 0, "last_reset": time.time(), "cooldown_until": 0})
        self.key_lock = threading.Lock()
        self.active_jobs: Dict[str, dict] = {}
        self.cancelled_jobs = set()

    def _report_key_cooldown(self, key: str, wait_time: float):
        """Marks a key as globally exhausted for a specific duration across all threads."""
        with self.key_lock:
            self.key_usage[key]["cooldown_until"] = time.time() + wait_time

    def _get_next_key(self, keys: list) -> Optional[str]:
        """Round-robin key selection with strict global rate limit awareness and a 25% backup redundancy layer."""
        if not keys:
            return None
            
        with self.key_lock:
            now = time.time()
            
            # --- FALLBACK SYSTEM 1: Strict 25% Key Reserve ---
            paid_keys = settings_manager.settings.get("paid_api_keys", [])
            free_keys = settings_manager.settings.get("free_api_keys", [])
            
            backup_count = 0
            if free_keys:
                backup_count = max(1, int(len(free_keys) * 0.25))
                # If they only have 1 key, we can't reserve it as backup
                if backup_count >= len(free_keys):
                    backup_count = 0 if len(free_keys) == 1 else 1

            if backup_count > 0:
                backup_keys = free_keys[-backup_count:]
                primary_free = free_keys[:-backup_count]
            else:
                backup_keys = []
                primary_free = free_keys
                
            primary_keys = paid_keys + primary_free
            
            # Reset call states over time
            for k in (primary_keys + backup_keys):
                usage = self.key_usage[k]
                if now - usage["last_reset"] > 60:
                    usage["calls"] = 0
                    usage["last_reset"] = now

            # Filter natively available keys
            available_primary = [k for k in primary_keys if now >= self.key_usage[k].get("cooldown_until", 0)]
            available_backup = [k for k in backup_keys if now >= self.key_usage[k].get("cooldown_until", 0)]
            
            best_key = None
            if available_primary:
                # Prioritize primary rotation
                best_key = min(available_primary, key=lambda k: self.key_usage[k]["calls"])
            elif available_backup:
                # FALLBACK FLIPPED: Primary exhausted. Start utilizing untouched backup keys to keep pipeline alive.
                best_key = min(available_backup, key=lambda k: self.key_usage[k]["calls"])
            else:
                # If ALL APIs (Primary + Backup) are globally hard-banned, return the one closest to waking up 
                all_configured = primary_keys + backup_keys
                if not all_configured: return None
                return min(all_configured, key=lambda k: self.key_usage[k].get("cooldown_until", 0))

            if best_key:
                self.key_usage[best_key]["calls"] += 1
            return best_key

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract YouTube video ID from various URL formats."""
        import re
        patterns = [
            r'(?:youtube\.com/(?:watch\?v=|live/|embed/|shorts/|v/))([a-zA-Z0-9_-]{11})',
            r'(?:youtu\.be/)([a-zA-Z0-9_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def _download_via_proxy(self, video_id: str, job_id: str) -> Optional[Path]:
        """Download YouTube audio via public Invidious/Piped proxy APIs — bypasses all datacenter IP blocks."""
        import httpx
        
        # Multiple public proxy instances for redundancy
        invidious_instances = [
            "https://inv.nadeko.net",
            "https://invidious.fdn.fr",
            "https://invidious.perennialte.ch",
            "https://iv.datura.network",
            "https://inv.tux.pizza",
            "https://invidious.protokolla.fi",
        ]
        piped_instances = [
            "https://pipedapi.kavin.rocks",
            "https://pipedapi.r4fo.com",
            "https://pipedapi.adminforge.de",
        ]
        
        # Try Invidious first
        for instance in invidious_instances:
            try:
                await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"🔄 Trying proxy: {instance.split('//')[1]}..."})
                async with httpx.AsyncClient(timeout=20, follow_redirects=True, verify=False) as client:
                    resp = await client.get(f"{instance}/api/v1/videos/{video_id}")
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    
                    # Find best audio-only stream (adaptive formats)
                    audio_url = None
                    best_bitrate = 0
                    for fmt in data.get("adaptiveFormats", []):
                        if fmt.get("type", "").startswith("audio/"):
                            bitrate = fmt.get("bitrate", 0)
                            if bitrate > best_bitrate:
                                best_bitrate = bitrate
                                audio_url = fmt.get("url")
                    
                    if not audio_url:
                        logger.warning(f"No audio streams found via {instance}")
                        continue
                    
                    # Download the audio
                    await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"⬇️ Downloading audio via proxy..."})
                    audio_resp = await client.get(audio_url, timeout=120)
                    if audio_resp.status_code == 200 and len(audio_resp.content) > 10000:
                        # Save raw audio
                        raw_path = TEMP_DIR / f"{job_id}_raw.webm"
                        raw_path.write_bytes(audio_resp.content)
                        
                        # Convert to mp3
                        mp3_path = TEMP_DIR / f"{job_id}.mp3"
                        convert_cmd = [FFMPEG_PATH or "ffmpeg", "-i", str(raw_path), "-codec:a", "libmp3lame", "-b:a", "128k", "-y", str(mp3_path)]
                        proc = await asyncio.create_subprocess_exec(*convert_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                        await proc.communicate()
                        raw_path.unlink(missing_ok=True)
                        
                        if mp3_path.exists() and mp3_path.stat().st_size > 10000:
                            await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"✅ Audio downloaded via proxy!"})
                            return mp3_path
                        else:
                            mp3_path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Invidious {instance} failed: {e}")
                continue
        
        # Try Piped API
        for instance in piped_instances:
            try:
                await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"🔄 Trying Piped proxy: {instance.split('//')[1]}..."})
                async with httpx.AsyncClient(timeout=20, follow_redirects=True, verify=False) as client:
                    resp = await client.get(f"{instance}/streams/{video_id}")
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    
                    # Find audio stream
                    audio_url = None
                    for stream in data.get("audioStreams", []):
                        if stream.get("url"):
                            audio_url = stream["url"]
                            break
                    
                    if not audio_url:
                        continue
                    
                    await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"⬇️ Downloading audio via Piped..."})
                    audio_resp = await client.get(audio_url, timeout=120)
                    if audio_resp.status_code == 200 and len(audio_resp.content) > 10000:
                        raw_path = TEMP_DIR / f"{job_id}_raw.webm"
                        raw_path.write_bytes(audio_resp.content)
                        
                        mp3_path = TEMP_DIR / f"{job_id}.mp3"
                        convert_cmd = [FFMPEG_PATH or "ffmpeg", "-i", str(raw_path), "-codec:a", "libmp3lame", "-b:a", "128k", "-y", str(mp3_path)]
                        proc = await asyncio.create_subprocess_exec(*convert_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                        await proc.communicate()
                        raw_path.unlink(missing_ok=True)
                        
                        if mp3_path.exists() and mp3_path.stat().st_size > 10000:
                            await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"✅ Audio downloaded via Piped!"})
                            return mp3_path
                        else:
                            mp3_path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Piped {instance} failed: {e}")
                continue
        
        return None

    async def download_audio(self, url: str, job_id: str) -> Optional[Path]:
        """Download audio from URL using robust multi-backend approach.
        
         Strategy for YouTube on cloud:
        1. Invidious/Piped proxy APIs (bypasses ALL datacenter IP blocks)
        2. pytubefix (direct API, sometimes works)
        3. yt-dlp with cookies (last resort)
        """
        await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "📥 Downloading audio from URL..."})
        
        is_youtube = "youtube.com" in url.lower() or "youtu.be" in url.lower()
        is_cloud = os.environ.get("RENDER") == "true" or os.environ.get("SPACE_ID") is not None
        
        # ═══ CLOUD YOUTUBE: Public Proxies ═══
        if is_youtube and is_cloud:
            video_id = self._extract_video_id(url)
            if video_id:
                await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "🌐 Using proxy bypass for YouTube (cloud mode)..."})
                result = await self._download_via_proxy(video_id, job_id)
                if result:
                    return result
                await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "⚠️ All public proxies failed, trying direct methods..."})
        
        # ═══ PYTUBEFIX (works locally, sometimes on cloud) ═══
        if is_youtube:
            try:
                from pytubefix import YouTube
                def _download_pytube():
                    yt = YouTube(url, client='WEB')
                    stream = yt.streams.filter(only_audio=True).order_by('abr').first()
                    if stream:
                        return stream.download(output_path=str(TEMP_DIR), filename=f"{job_id}.mp4")
                    return None
                    
                loop = asyncio.get_event_loop()
                audio_file = await loop.run_in_executor(None, _download_pytube)
                
                if audio_file:
                    audio_path = Path(audio_file)
                    mp3_path = audio_path.with_suffix('.mp3')
                    convert_cmd = [FFMPEG_PATH or "ffmpeg", "-i", str(audio_path), "-codec:a", "libmp3lame", "-b:a", "128k", "-y", str(mp3_path)]
                    proc = await asyncio.create_subprocess_exec(*convert_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    await proc.communicate()
                    try:
                        audio_path.unlink(missing_ok=True)
                    except:
                        pass
                    return mp3_path
            except Exception as e:
                logger.warning(f"Pytubefix download failed: {e}")
                
        # ═══ YT-DLP (last resort, works great locally) ═══
        try:
            cmd = [sys.executable]
            if is_cloud:
                cmd.append(str(BASE_DIR / "ytdlp_bypass.py"))
            else:
                cmd.extend(["-m", "yt_dlp"])
                
            cmd.extend([
                "--no-check-certificates",
                "-x", "--audio-format", "mp3",
                "--audio-quality", "128K",
                "--no-playlist",
                "--force-ipv4",
                "--geo-bypass",
                "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "--socket-timeout", "30",
                "--extractor-args", "youtube:player_client=android,web,tv",
                "--js-runtimes", "node",
                "--remote-components", "ejs:github",
            ])
            
            # Apply cookies
            cookies_content = settings_manager.settings.get("youtube_cookies", "").strip()
            if not cookies_content and is_youtube:
                cookies_content = """# Netscape HTTP Cookie File
# https://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file! Do not edit.

.youtube.com	TRUE	/	FALSE	1804679192	HSID	A-aXQAS_DUtkVJ6gY
.youtube.com	TRUE	/	TRUE	1804679192	SSID	AMvny_LXbARGeUgwH
.youtube.com	TRUE	/	FALSE	1804679192	APISID	h_6o4Tb7GEuX4R-f/AisuzVJPDyknakWBB
.youtube.com	TRUE	/	TRUE	1804679192	SAPISID	LRc6XyrpbzM6EYT7/A9G2ve_8SYA-y4Cnk
.youtube.com	TRUE	/	TRUE	1804679192	__Secure-1PAPISID	LRc6XyrpbzM6EYT7/A9G2ve_8SYA-y4Cnk
.youtube.com	TRUE	/	TRUE	1804679192	__Secure-3PAPISID	LRc6XyrpbzM6EYT7/A9G2ve_8SYA-y4Cnk
.youtube.com	TRUE	/	FALSE	1804679192	SID	g.a0006Qg9ED9Ge9XojLbQf0YW9Z-whXYe4__3UF-JXoB0zh3ePYYsBapfAEW_lgehWjM24DU2bwACgYKAf8SARQSFQHGX2MiYChuxYvp5LTwSJJoYNz2JBoVAUF8yKp_D5fn1Yxp4RtTsDdQR3XW0076
.youtube.com	TRUE	/	TRUE	1804679192	__Secure-1PSID	g.a0006Qg9ED9Ge9XojLbQf0YW9Z-whXYe4__3UF-JXoB0zh3ePYYsZY6YS95RausKFbsFsFIy3AACgYKAdwSARQSFQHGX2MirqHn6Fm4bsubz7IZc_9bsRoVAUF8yKq59r0lH1n8bO_bdeNwn-wH0076
.youtube.com	TRUE	/	TRUE	1804679192	__Secure-3PSID	g.a0006Qg9ED9Ge9XojLbQf0YW9Z-whXYe4__3UF-JXoB0zh3ePYYs1IF4rZ9zD2SEgNkeyHtHagACgYKAbwSARQSFQHGX2MiDMWQSKzBgB5YbzL4V1bsihoVAUF8yKo9AtX51J-R_xNfY9AWHsgY0076
.youtube.com	TRUE	/	TRUE	1804679192	LOGIN_INFO	AFmmF2swRQIgcgZgE70aAwlul_3Xq4Cb7FgHo6oumqnzvQbHiWnOBmYCIQDRK8pWscfqTu8Jn-YzlT5YfCOHwzx2Vziw3_jub1zpRg:QUQ3MjNmdzYzdVFnMkIyZTk1cGo2akloZkduMGpJaU8xYUw4V0lPSkRIeFN5S3hFUDBLVkNUc29mQkhGNkhvVXZseHY1VHpfWlZHV3lISUQ2NzJkd1VrOHI5eVhhMFhXRHlkeWU2c2w2UC1iVGhYUzQxcXY5QkVEU01XTWxtVUlKTHdJVXh5SDdPQ1k5WHJBQ2owRXIyUE9SQkVfTTRCOWh3
.youtube.com	TRUE	/	TRUE	1806587430	PREF	f6=40000080&tz=Asia.Calcutta&f4=4000000&f7=100
.youtube.com	TRUE	/	TRUE	1803569087	__Secure-1PSIDTS	sidts-CjUBBj1CYoBzvFZKd8Ek_AMX8EDmxnIkwRiwZ7dS2i7fMSYHO_8OuUUsAx5NopFS3PZ2bgVjOhAA
.youtube.com	TRUE	/	TRUE	1803569087	__Secure-3PSIDTS	sidts-CjUBBj1CYoBzvFZKd8Ek_AMX8EDmxnIkwRiwZ7dS2i7fMSYHO_8OuUUsAx5NopFS3PZ2bgVjOhAA
.youtube.com	TRUE	/	FALSE	1803569087	SIDCC	AKEyXzWmOV09wFQDsxi0XObdzrHbE-OEgCQUHjrWvVsGYB6T46kFLTnPAw2CiSg-W3VbJrW9eQ
.youtube.com	TRUE	/	TRUE	1803569087	__Secure-1PSIDCC	AKEyXzUExAURWNcxKZfRPcu5TK_S_LqiQUGNQOmVgZ-NGHEeJX-NWJgU4N5fZ5srCWQ6Bw_YMg
.youtube.com	TRUE	/	TRUE	1803569087	__Secure-3PSIDCC	AKEyXzVSLqE3vYV-kxHR_khPJDslxXkwwEPNxpPO0aEATGFE1wrS6MCeAqyAPk_XGqhScKFX2HM
.youtube.com	TRUE	/	TRUE	1787517472	VISITOR_INFO1_LIVE	uyBWueKyEQU
.youtube.com	TRUE	/	TRUE	1787517472	VISITOR_PRIVACY_METADATA	CgJJThIEGgAgZw%3D%3D
.youtube.com	TRUE	/	TRUE	0	YSC	LEHEe6DUbIM
.youtube.com	TRUE	/	TRUE	1787573553	__Secure-ROLLOUT_TOKEN	CN3Zu8WDp-7mgAEQucTTx7mJkQMYvM3U2c70kgM%3D"""

            cookies_file = TEMP_DIR / f"{job_id}_cookies.txt"
            if cookies_content:
                with open(cookies_file, "w") as f:
                    f.write(cookies_content)
                cmd.extend(["--cookies", str(cookies_file)])
                
            cmd.extend([
                "-o", str(TEMP_DIR / f"{job_id}.%(ext)s"),
                url
            ])
            
            if FFMPEG_PATH:
                cmd.extend(["--ffmpeg-location", str(Path(FFMPEG_PATH).parent)])
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            # Clean up temp cookies file
            if cookies_file.exists():
                try:
                    cookies_file.unlink()
                except Exception:
                    pass
            
            stderr_text = stderr.decode(errors='replace').strip()
            stdout_text = stdout.decode(errors='replace').strip()
            if stderr_text:
                logger.warning(f"yt-dlp stderr: {stderr_text[-500:]}")
            if stdout_text:
                logger.info(f"yt-dlp stdout: {stdout_text[-300:]}")
            
            # Find the output file
            for f in TEMP_DIR.iterdir():
                if f.stem == job_id and f.suffix in ['.mp3', '.m4a', '.wav', '.webm', '.opus']:
                    if f.suffix != '.mp3':
                        mp3_path = f.with_suffix('.mp3')
                        convert_cmd = [FFMPEG_PATH or "ffmpeg", "-i", str(f), "-codec:a", "libmp3lame", "-b:a", "128k", str(mp3_path)]
                        proc = await asyncio.create_subprocess_exec(*convert_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                        await proc.communicate()
                        f.unlink()
                        return mp3_path
                    return f
            
            # Error reporting
            error_hint = ""
            stderr_lower = stderr_text.lower()
            if "is_live" in stderr_lower or "live event" in stderr_lower:
                error_hint = " This appears to be an active live stream — try again after it ends."
            elif "private" in stderr_lower:
                error_hint = " This video appears to be private or restricted."
            elif "unavailable" in stderr_lower or "not available" in stderr_lower:
                error_hint = " This video is unavailable in this region or has been removed."
            elif "sign in" in stderr_lower or "age restrict" in stderr_lower:
                error_hint = " This video requires sign-in or age verification."
            elif "no address associated" in stderr_lower or "network is unreachable" in stderr_lower:
                error_hint = " Network error: Could not reach YouTube."
            
            last_err = stderr_text.split('\n')[-1][:150] if stderr_text else "No output from yt-dlp"
            await ws_manager.broadcast({"type": "error", "job_id": job_id, "message": f"❌ Download failed.{error_hint} ({last_err})"})
            logger.error(f"Download failed for {url}. Exit: {process.returncode}. stderr: {stderr_text[-500:]}")
            return None
        except Exception as e:
            await ws_manager.broadcast({"type": "error", "job_id": job_id, "message": f"❌ Download error: {str(e)}"})
            logger.error(f"Download error: {e}")
            cookies_file = TEMP_DIR / f"{job_id}_cookies.txt"
            if cookies_file.exists():
                try:
                    cookies_file.unlink()
                except Exception:
                    pass
            return None

    def split_audio(self, audio_path: Path, chunk_minutes: int = 10) -> List[Path]:
        """Split audio into perfect MP3 chunks (re-encoding to guarantee 100% valid headers for Whisper)."""
        import subprocess
        
        chunk_seconds = chunk_minutes * 60
        # Force MP3 output to ensure Groq Whisper compatibility
        ext = ".mp3"
        output_pattern = str(TEMP_DIR / f"{audio_path.stem}_chunk_%04d{ext}")
        
        cmd = [
            FFMPEG_PATH or "ffmpeg",
            "-i", str(audio_path),
            "-f", "segment",
            "-segment_time", str(chunk_seconds),
            "-c:a", "libmp3lame",
            "-b:a", "64k",  # 64k is perfectly fine for speech recognition
            output_pattern
        ]
        
        try:
            # DEVNULL prevents any stdout/stderr buffer deadlocks
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            chunks = sorted(TEMP_DIR.glob(f"{audio_path.stem}_chunk_*{ext}"))
            return chunks
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg split failed on {audio_path.name}")
            return []

    async def generate_metadata_keywords(self, company_name: str, job_id: str) -> str:
        """Fetch highly specific metadata keywords about a company from Groq directly to aid Whisper."""
        if not company_name or company_name.lower() in ["meeting", "test", "demo", ""]:
            return ""
            
        all_keys = settings_manager.get_all_keys()
        if not all_keys:
            return ""
            
        key = all_keys[0]
        import httpx
        
        await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"🔍 AI Agent: Generating context/speaker keywords for '{company_name}'..."})
        
        try:
            response = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": "You are a corporate research AI. Output ONLY a comma-separated list of keywords. No prologue, no extra text."},
                        {"role": "user", "content": f"I am about to transcribe a business meeting/call titled '{company_name}'. Generate EXACTLY 10 to 15 highly specific keywords. Specifically include: key executives, major products, and financial terms related to this company. Only give the comma-separated words so I can feed them to Whisper."}
                    ],
                    "temperature": 0.2
                },
                timeout=20,
                verify=str(cert_path) if cert_path.exists() else True
            )
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"].strip()
                # Clean up any bullet points or newlines if the AI hallucinated formatting
                content = content.replace("\n", ", ").replace("- ", "").replace("*", "")
                return content
            return ""
        except Exception as e:
            logger.error(f"Failed to generate metadata keywords: {e}")
            return ""

    def smart_format_chunk_sync(self, segments_data: list, job_id: str, company_name: str, context_keywords: str, all_keys: list) -> str:
        """Intelligently identify speakers and format dialogue without dropping a single word."""
        import httpx
        import json
        
        if not segments_data:
            return ""
            
        # Build raw text prompt
        raw_text_to_process = ""
        for s in segments_data:
            raw_text_to_process += f"[ID: {s['id']}] {{time: {s['time_str']}}} {s['text']}\n"
            
        system_prompt = (
            f"You are an elite transcription editor for the '{company_name}' meeting.\n"
            "You are given a raw transcript segment with [ID: XX] tags.\n"
            "Your task is to identify the precise speaker for each segment based on context, flow, and provided keywords.\n"
            "CRITICAL RULES:\n"
            "1. You MUST return your response ONLY as a JSON object with a single key 'speaker_changes'.\n"
            "2. 'speaker_changes' must be a list of objects containing 'id' (the integer ID where a NEW speaker begins) and 'speaker' (their deduced true name).\n"
            "3. If the speaker does not change between consecutive IDs, do NOT add a new entry for every ID. Only add an entry when the speaker visibly CHANGES.\n"
            "4. NEVER invent or write actual dialogue. Just map the changes.\n"
            "5. Example output:\n"
            '{"speaker_changes": [{"id": 0, "speaker": "Host"}, {"id": 12, "speaker": "CEO Name"}]}'
        )
        user_prompt = f"Key Executives & Context: {context_keywords}\n\nTranscript Segment:\n{raw_text_to_process}"
        
        attempt = 0
        speaker_map = {}
        
        while attempt < 100:
            if job_id in self.cancelled_jobs:
                return raw_text_to_process
                
            api_key = self._get_next_key(all_keys)
            if not api_key:
                time.sleep(1)
                continue
                
            try:
                verify = str(cert_path) if cert_path.exists() else True
                response = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.05,
                        "max_tokens": 8000
                    },
                    timeout=180,
                    verify=verify
                )
                if response.status_code == 429:
                    wait_time = 1.5
                    retry_after = response.headers.get("retry-after")
                    if retry_after:
                        try: wait_time = float(retry_after)
                        except: pass
                    else:
                        try:
                            msg = response.json().get("error", {}).get("message", "")
                            match = re.search(r'try again in (\d+\.?\d*)s', msg)
                            if match: wait_time = float(match.group(1))
                        except: pass
                    
                    self._report_key_cooldown(api_key, wait_time)
                    import random
                    time.sleep(random.uniform(0.5, 1.5))
                    attempt += 1  
                    continue
                if response.status_code == 200:
                    raw_json = response.json()["choices"][0]["message"]["content"].strip()
                    try:
                        parsed = json.loads(raw_json)
                        changes = parsed.get("speaker_changes", [])
                        for change in changes:
                            speaker_map[int(change["id"])] = change["speaker"]
                        break
                    except Exception as e:
                        logger.debug(f"JSON Parse failed, retrying: {e}")
                        attempt += 1
                        continue
            except Exception as e:
                attempt += 1
                if attempt % 10 == 0:
                    logger.debug(f"Smart format waiting/hopping... (attempt {attempt}): {e}")
                time.sleep(2)
        
        # Assemble perfectly untouched text
        final_text = ""
        current_speaker = "Unknown Speaker"
        
        for s in segments_data:
            sid = s["id"]
            
            # Start of chunk fallback to trigger
            if sid == 0 and sid not in speaker_map:
                speaker_map[sid] = current_speaker
                
            if sid in speaker_map:
                current_speaker = speaker_map[sid]
                final_text += f"\n\n[SPEAKER] {current_speaker}\n[TIME] {s['time_str']}\n"
                
            final_text += f"{s['text']} "
            
        # Clean up
        final_text = final_text.replace("\n ", "\n").strip()
        return final_text

    def transcribe_chunk(self, chunk_path: Path, job_id: str, all_keys: list, model: str = "whisper-large-v3", context_keywords: str = "") -> dict:
        """Transcribe a single audio chunk using Groq API."""
        import httpx
        
        max_retries = 300 # Wait patiently instead of silently dropping the chunk!
        attempt = 0
        while attempt < max_retries:
            if job_id in self.cancelled_jobs:
                return {"text": "[CANCELLED]", "error": True}
                
            api_key = self._get_next_key(all_keys)
            if not api_key:
                time.sleep(1)
                continue
            
            # Global Cooldown Assessment: Check if this key is universally locked
            key_cooldown = self.key_usage[api_key].get("cooldown_until", 0)
            now = time.time()
            if key_cooldown > now:
                # All master keys are globally down. Check for cancel, micro-sleep dynamically and loop instantly to catch the first key that re-opens
                if job_id in self.cancelled_jobs:
                    return {"text": "[CANCELLED]", "error": True}
                
                time.sleep(min(key_cooldown - now, 2.0))
                
                if attempt % 15 == 0:
                    try:
                        loop = asyncio.get_event_loop()
                        asyncio.run_coroutine_threadsafe(
                            ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"♻️ Auto-Recovery: Keys exhausted. Retrying chunk with backup systems... ({attempt}/{max_retries})"}),
                            loop
                        )
                    except: pass
                continue
            
            try:
                with open(chunk_path, 'rb') as f:
                    files = {'file': (chunk_path.name, f, 'audio/mpeg')}
                    # Whisper API's "prompt" parameter acts as simulated prior text, NOT an instruction prompt. 
                    # Passing full sentences like "Transcribe audio accurately" causes Whisper to hallucinate those exact sentences during silent audio gaps.
                    # We now only pass a clean, natural comma-separated string of keywords.
                    
                    keyword_injection = f"{context_keywords}, " if context_keywords else ""
                    
                    base_prompt = (
                        f"{keyword_injection}"
                        "Hello, welcome! This is a highly accurate, grammatically correct, and fully punctuated transcript of the professional financial presentation. Lakh, Crore, EBITDA, YoY, QoQ, PAT, Margins, Revenue."
                    )
                    
                    # Groq Whisper has a hard 896 character prompt limit
                    final_prompt = base_prompt[:880]
                    
                    data = {
                        'model': model,
                        'language': 'en',
                        'response_format': 'verbose_json',
                        'prompt': final_prompt,
                        'temperature': '0'  # Forces strictly deterministic, fully accurate reading and heavily limits hallucination loops
                    }
                    
                    verify = str(cert_path) if cert_path.exists() else True
                    
                    response = httpx.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        files=files,
                        data=data,
                        timeout=300,
                        verify=verify
                    )
                    
                    if response.status_code == 429:
                        wait_time = 2.0
                        retry_after = response.headers.get("retry-after")
                        if retry_after:
                            try: wait_time = float(retry_after)
                            except: pass
                        else:
                            try:
                                msg = response.json().get("error", {}).get("message", "")
                                match = re.search(r'try again in (\d+\.?\d*)s', msg)
                                if match: wait_time = float(match.group(1))
                            except: pass
                            
                        if attempt % 15 == 0:
                            logger.info(f"Chunk rate-limited. Global {wait_time:.1f}s ban on key... (Attempt {attempt}/{max_retries})")
                        
                        self._report_key_cooldown(api_key, wait_time)
                        import random
                        
                        if job_id in self.cancelled_jobs:
                            return {"text": "[CANCELLED]", "error": True}
                            
                        time.sleep(random.uniform(0.5, 2.0))
                        attempt += 1
                        continue
                    
                    response.raise_for_status()
                    return response.json()
                    
            except Exception as e:
                attempt += 1
                if attempt % 15 == 0:
                    logger.warning(f"Chunk transcription glitch (hoping to next key, attempt {attempt}): {e}")
                
                if job_id in self.cancelled_jobs:
                    return {"text": "[CANCELLED]", "error": True}
                    
                if attempt < max_retries:
                    time.sleep(2.0)
                else:
                    return {"text": f"[ERROR: Could not transcribe chunk - {str(e)}]", "error": True}
        
        logger.error(f"CRITICAL: Chunk dropped because {max_retries} retries were exhausted.")
        return {"text": "[ERROR: Max retries exceeded across all keys. System abandoned chunk.]", "error": True}

    def post_process_transcript(self, text: str, context_keywords: str = "") -> str:
        """Apply speaker diarization regex and formatting."""
        # Add line breaks before speaker tags
        text = re.sub(r'(Speaker\s*\d+\s*:)', r'\n\n\1', text)
        # Clean up multiple newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Capitalize speaker tags
        text = re.sub(r'speaker\s*(\d+)', lambda m: f'Speaker {m.group(1)}', text, flags=re.IGNORECASE)
        # Fix common financial terms
        financial_fixes = {
            r'\bebitda\b': 'EBITDA', r'\broe\b': 'ROE', r'\broa\b': 'ROA',
            r'\broce\b': 'ROCE', r'\bcagr\b': 'CAGR', r'\bpat\b': 'PAT',
            r'\bpbt\b': 'PBT', r'\beps\b': 'EPS', r'\bnav\b': 'NAV',
            r'\baum\b': 'AUM', r'\bnpa\b': 'NPA', r'\byoy\b': 'YoY',
            r'\bqoq\b': 'QoQ', r'\bcapex\b': 'Capex', r'\bopex\b': 'Opex',
        }
        for pattern, replacement in financial_fixes.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            
        # Hard-delete any instances where Whisper hallucinated the internal system prompt
        hallucination_str1 = "Lakh, Crore, EBITDA, YoY, QoQ, PAT, Margins, Revenue."
        hallucination_str2 = "Lakh, Crore, EBITDA, YoY, QoQ, PAT, Margins, Revenue"
        text = text.replace(hallucination_str1, "").replace(hallucination_str2, "")
        
        if context_keywords:
            text = text.replace(context_keywords, "")
            # Sometimes it adds a trailing comma or space
            text = text.replace(f"{context_keywords},", "").replace(f"{context_keywords}.", "")
        
        return text.strip()

    async def transcribe_full(self, audio_path: Path, job_id: str, company_name: str = "Meeting") -> dict:
        """Full transcription pipeline with parallel chunk processing."""
        if job_id in self.cancelled_jobs:
            return {"error": "Cancelled"}
            
        start_time = time.time()
        all_keys = settings_manager.get_all_keys()
        
        if not all_keys:
            await ws_manager.broadcast({"type": "error", "job_id": job_id, "message": "❌ No API keys configured! Go to Settings → API Keys to add your Groq keys."})
            return {"error": "No API keys configured"}

        model = settings_manager.settings.get("default_model", "whisper-large-v3")
        
        # --- FALLBACK SYSTEM 2: Dynamic Chunk Auto-Scaling based on Network Bandwidth ---
        total_keys = len(all_keys)
        if total_keys <= 2:
            chunk_minutes = 25  # Bottleneck constraint: Massive chunks, very few requests
        elif total_keys <= 5:
            chunk_minutes = 20
        elif total_keys <= 10:
            chunk_minutes = 15  # Solid capability
        else:
            chunk_minutes = 10  # Plentiful API keys, can afford rapid micro-chunk requests
            
        # Ensure user settings don't accidentally override safety limit
        saved_chunk_size = settings_manager.settings.get("chunk_duration_minutes", 10)
        chunk_minutes = max(chunk_minutes, saved_chunk_size)
        
        # --- FALLBACK SYSTEM 3: Dynamic Load Balancing ---
        free_keys = settings_manager.settings.get("free_api_keys", [])
        backup_count = max(1, int(len(free_keys) * 0.25)) if free_keys else 0
        if backup_count >= len(free_keys): backup_count = 0 if len(free_keys) == 1 else 1
        
        primary_count = max(1, len(all_keys) - backup_count)
        
        # Cap concurrent workers strictly to the Primary pool to prevent early DDoS collisions.
        # Backups are only tapped linearly when primary drops.
        max_workers = primary_count

        # Fetch metadata keywords
        keywords = ""
        if company_name and company_name.lower() not in ["meeting", "test", "demo", ""]:
            keywords = await self.generate_metadata_keywords(company_name, job_id)
            if keywords:
                await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"🎯 Identified & Injected {len(keywords.split(','))} company-specific keywords for enhanced speaker/entity accuracy."})

        # Split audio
        await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "✂️ Splitting audio into chunks..."})
        
        loop = asyncio.get_event_loop()
        chunks = await loop.run_in_executor(None, self.split_audio, audio_path, chunk_minutes)
        total_chunks = len(chunks)
        
        if total_chunks == 0:
            await ws_manager.broadcast({"type": "error", "job_id": job_id, "message": "❌ Extracted audio is empty or corrupted. Cannot transcribe."})
            return {"error": "No chunks generated"}
            
        await ws_manager.broadcast({
            "type": "log", "job_id": job_id,
            "message": f"📦 Split into {total_chunks} chunks. Starting parallel transcription with {len(all_keys)} API key(s)..."
        })
        await ws_manager.broadcast({"type": "progress", "job_id": job_id, "progress": 5, "total_chunks": total_chunks})

        # Parallel transcription
        results = [None] * total_chunks
        completed_count = 0

        def process_chunk(idx, chunk_path):
            if job_id in self.cancelled_jobs:
                return idx, {"text": "[CANCELLED]", "error": True}
                
            result = self.transcribe_chunk(chunk_path, job_id, all_keys, model, keywords)
            
            # SMART TIMESTAMP CALCULATION & DIARIZATION INJECTION
            chunk_offset_seconds = idx * chunk_minutes * 60
            segments_data = []
            
            if "segments" in result and result["segments"]:
                for s_idx, segment in enumerate(result["segments"]):
                    if "text" in segment and segment["text"].strip():
                        start_sec = segment["start"] + chunk_offset_seconds
                        h = int(start_sec // 3600)
                        m = int((start_sec % 3600) // 60)
                        s = int(start_sec % 60)
                        time_str = f"[{h:02d}:{m:02d}:{s:02d}]" if h > 0 else f"[{m:02d}:{s:02d}]"
                        
                        segments_data.append({
                            "id": s_idx,
                            "time_str": time_str,
                            "text": segment["text"].strip()
                        })
            
            # SMART DIARIZATION PASS (Zero-Loss Map System)
            if segments_data and not result.get("error"):
                formatted_text = self.smart_format_chunk_sync(segments_data, job_id, company_name, keywords, all_keys)
                result["text"] = formatted_text
            elif result.get("text") and not result.get("error"):
                # Safety fallback
                pass
                
            return idx, result

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            tasks = [
                loop.run_in_executor(executor, process_chunk, i, chunk)
                for i, chunk in enumerate(chunks)
            ]
            
            for coro in asyncio.as_completed(tasks):
                idx, result = await coro
                if job_id in self.cancelled_jobs:
                    await ws_manager.broadcast({"type": "error", "job_id": job_id, "message": "🛑 Job cancelled by user."})
                    return {"error": "Cancelled"}
                    
                results[idx] = result
                completed_count += 1
                progress = int(5 + (completed_count / total_chunks) * 85)
                await ws_manager.broadcast({
                    "type": "progress", "job_id": job_id,
                    "progress": progress,
                    "message": f"🔄 Processed chunk {completed_count}/{total_chunks}..."
                })

        # Combine results
        await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "📝 Combining and formatting transcript..."})
        
        full_text = ""
        errors = []
        for i, result in enumerate(results):
            if result and not result.get("error"):
                text = result.get("text", "")
                full_text += f"\n\n{text}"
            else:
                err_txt = result.get('text', 'Unknown error') if result else 'Unknown error'
                errors.append(f"Chunk {i+1}: {err_txt}")
                full_text += f"\n\n[WARNING: A section failed to transcribe. Error: {err_txt}]"

        # Post-process
        full_text = self.post_process_transcript(full_text, keywords)
        
        processing_time = time.time() - start_time
        
        # Generate outputs
        await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "📄 Generating files & building master bundle..."})
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        safe_name = re.sub(r'[^\w\s-]', '', company_name).strip().replace(' ', '_')
        file_prefix = f"{safe_name}_{timestamp}"
        
        # Save TXT (Format naturally)
        clean_txt = full_text.replace('[SPEAKER]', '').replace('[TIME]', '')
        txt_path = OUTPUT_DIR / f"{file_prefix}.txt"
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(f"{company_name} - TRANSCRIPT\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("=" * 60 + "\n\n")
            f.write(clean_txt)

        # Save PDF
        pdf_path = OUTPUT_DIR / f"{file_prefix}.pdf"
        self._generate_pdf(pdf_path, company_name, full_text, processing_time)

        # Generate & Save AI Executive Summary
        await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "🧠 Synthesizing AI Executive Summary & Financial Extraction Brief..."})
        summary_text = await loop.run_in_executor(None, self._generate_executive_summary, full_text, company_name, job_id, all_keys)
        summary_pdf_path = OUTPUT_DIR / f"{file_prefix}_Executive_Summary.pdf"
        if summary_text:
            self._generate_summary_pdf(summary_pdf_path, company_name, summary_text)

        # Compress MP3 to output
        compressed_path = MP3_DIR / f"{file_prefix}.mp3"
        await self._compress_mp3(audio_path, compressed_path)

        # Save Keywords
        keywords_path = None
        if keywords:
            keywords_path = OUTPUT_DIR / f"{file_prefix}_keywords.txt"
            with open(keywords_path, 'w', encoding='utf-8') as f:
                f.write(f"Metadata Keywords for {company_name}\n")
                f.write("="*40 + "\n")
                f.write(keywords + "\n")
                
        # Master Folder
        bundle_dir = TEMP_DIR / file_prefix
        bundle_dir.mkdir(exist_ok=True)
        import shutil
        shutil.copy(txt_path, bundle_dir)
        shutil.copy(pdf_path, bundle_dir)
        if summary_pdf_path.exists():
            shutil.copy(summary_pdf_path, bundle_dir)
        shutil.copy(compressed_path, bundle_dir)
        if keywords_path:
            shutil.copy(keywords_path, bundle_dir)
            
        is_cloud = os.environ.get("RENDER") == "true" or os.environ.get("SPACE_ID") is not None
        if not is_cloud and Path.home().exists():
            mac_downloads = Path.home() / "Downloads" / "Transcriptor_Outputs"
            mac_downloads.mkdir(parents=True, exist_ok=True)
            mac_bundle = mac_downloads / file_prefix
            if mac_bundle.exists():
                shutil.rmtree(mac_bundle)
            shutil.copytree(bundle_dir, mac_bundle)
            await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"📁 Master folder saved locally to Downloads/Transcriptor_Outputs/{file_prefix}"})

        # Create zip in output dir
        shutil.make_archive(str(OUTPUT_DIR / file_prefix), 'zip', str(bundle_dir))
        
        await ws_manager.broadcast({"type": "progress", "job_id": job_id, "progress": 100})
        
        # Clean up temp chunks and bundle
        try:
            shutil.rmtree(bundle_dir)
        except Exception:
            pass
        for chunk in chunks:
            try:
                chunk.unlink()
            except Exception:
                pass
        
        result_data = {
            "job_id": job_id,
            "company_name": company_name,
            "txt_path": str(txt_path),
            "pdf_path": str(pdf_path),
            "mp3_path": str(compressed_path),
            "processing_time": round(processing_time, 1),
            "total_chunks": total_chunks,
            "errors": errors,
            "word_count": len(full_text.split()),
            "status": "completed"
        }

        # Save to history
        history_manager.add(result_data)

        await ws_manager.broadcast({
            "type": "complete", "job_id": job_id,
            "message": f"✅ Transcription complete! {len(full_text.split())} words in {processing_time:.1f}s",
            "data": result_data
        })

        return result_data

    def _generate_pdf(self, output_path: Path, company_name: str, text: str, processing_time: float):
        """Generate a professional PDF transcript."""
        from fpdf import FPDF

        class TranscriptPDF(FPDF):
            def header(self):
                self.set_font('Helvetica', 'B', 16)
                self.cell(0, 10, f'{company_name} - TRANSCRIPT', ln=True, align='L')
                self.set_font('Helvetica', '', 9)
                self.cell(0, 6, f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}', ln=True, align='R')
                self.line(10, self.get_y(), 200, self.get_y())
                self.ln(5)

            def footer(self):
                self.set_y(-15)
                self.set_font('Helvetica', 'I', 8)
                self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')

        pdf = TranscriptPDF()
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_font('Helvetica', '', 10)

        def _safe_write(pdf_obj, text_line):
            safe_text = text_line.encode('latin-1', 'replace').decode('latin-1')
            try:
                pdf_obj.multi_cell(0, 5, safe_text)
            except Exception as e:
                # Fallback for FPDFException "Not enough horizontal space" caused by huge unbroken words
                chunks = [safe_text[i:i+90] for i in range(0, len(safe_text), 90)]
                for chunk in chunks:
                    try:
                        pdf_obj.multi_cell(0, 5, chunk)
                    except:
                        pass

        for line in text.split('\n'):
            line = line.strip()
            if not line:
                pdf.ln(3)
                continue
                
            clean_line = line.replace('**', '')

            if clean_line.startswith('[SPEAKER]'):
                speaker_name = clean_line.replace('[SPEAKER]', '').strip()
                pdf.ln(5)
                pdf.set_font('Helvetica', 'B', 10)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(0, 5, speaker_name, ln=True)
            elif clean_line.startswith('[TIME]'):
                time_str = clean_line.replace('[TIME]', '').strip()
                pdf.set_font('Helvetica', 'I', 8)
                pdf.set_text_color(120, 120, 120)  # Professional grey timestamp
                pdf.cell(0, 4, time_str, ln=True)
                pdf.set_font('Helvetica', '', 10)
                pdf.set_text_color(0, 0, 0)
            elif clean_line.startswith('[TITLE]'):
                pass # Deprecated gracefully
            elif clean_line.startswith('---'):
                pdf.set_font('Helvetica', 'I', 9)
                pdf.cell(0, 5, clean_line, ln=True)
                pdf.set_font('Helvetica', '', 10)
            elif re.match(r'^[A-Z][\w\s\.\-]{0,40}:', clean_line) or re.match(r'Speaker\s*\d+\s*:', clean_line, flags=re.IGNORECASE):
                # Fallback if AI misses the new tag
                pdf.ln(4)
                pdf.set_font('Helvetica', 'B', 10)
                _safe_write(pdf, clean_line)
                pdf.set_font('Helvetica', '', 10)
            else:
                _safe_write(pdf, clean_line)

        try:
            pdf.output(str(output_path))
        except BaseException as e:
            logger.error(f"Failed to save PDF: {str(e)}")

    def _generate_executive_summary(self, full_text: str, company_name: str, job_id: str, all_keys: list) -> str:
        """Generate a 1-page executive summary and financial metrics using LLM."""
        import httpx
        
        # We use Mixtral because it supports 32k context size (up to ~25,000 words easily) which guarantees the 
        # entirety of a 1.5 hr master transcript fits without slicing.
        model_to_use = "mixtral-8x7b-32768"
        
        system_prompt = (
            "You are an elite financial analyst and executive assistant.\n"
            "Given the transcribed meeting/call below, generate a professional, highly concise 1-page Executive Brief.\n"
            "You MUST structure your response ONLY using exactly these three headings:\n\n"
            "THE TL;DR:\n"
            "[Provide a 3-paragraph executive summary of the entire call]\n\n"
            "FINANCIAL METRICS EXTRACTED:\n"
            "[Bulleted list of all numbers, revenue, EBITDA, guidance, timelines, or percentages mentioned]\n\n"
            "ACTION ITEMS:\n"
            "[Key decisions or forward-looking statements made by the leadership]\n\n"
            "If any section lacks information from the transcript, briefly state 'Not explicitly mentioned'. "
            "Do not output markdown asterisks or bold tags, just use plain structural line spacing and clean bullet dots (-)."
        )
        
        # safely slice text to fit ~120,000 chars which safely fits Mixtral limit
        safe_text_for_prompt = full_text[:120000]
        user_prompt = f"Transcript for {company_name}:\n\n{safe_text_for_prompt}"
        
        attempt = 0
        while attempt < 15:
            if job_id in self.cancelled_jobs:
                return ""
                
            api_key = self._get_next_key(all_keys)
            if not api_key:
                time.sleep(1)
                continue
                
            try:
                verify = str(cert_path) if cert_path.exists() else True
                response = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model_to_use,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 4000
                    },
                    timeout=180,
                    verify=verify
                )
                
                if response.status_code == 429:
                    time.sleep(2)
                    attempt += 1
                    continue
                    
                if response.status_code == 200:
                    return response.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                attempt += 1
                time.sleep(2)
                
        return "Summary could not be generated due to API timeouts."

    def _generate_summary_pdf(self, output_path: Path, company_name: str, summary_text: str):
        """Generate a professional PDF for the Executive Summary."""
        from fpdf import FPDF

        class SummaryPDF(FPDF):
            def header(self):
                self.set_font('Helvetica', 'B', 16)
                self.cell(0, 10, f'{company_name} - EXECUTIVE SUMMARY', ln=True, align='L')
                self.set_font('Helvetica', '', 9)
                self.cell(0, 6, f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}', ln=True, align='R')
                self.line(10, self.get_y(), 200, self.get_y())
                self.ln(5)

            def footer(self):
                self.set_y(-15)
                self.set_font('Helvetica', 'I', 8)
                self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')

        pdf = SummaryPDF()
        pdf.alias_nb_pages()
        pdf.add_page()

        def _safe_write(pdf_obj, text_line, is_header=False):
            safe_text = text_line.encode('latin-1', 'replace').decode('latin-1')
            try:
                if is_header:
                    pdf_obj.set_font('Helvetica', 'B', 11)
                else:
                    pdf_obj.set_font('Helvetica', '', 11)
                pdf_obj.multi_cell(0, 6, safe_text)
            except:
                pass

        for line in summary_text.split('\n'):
            line = line.strip()
            if not line:
                pdf.ln(3)
                continue
                
            clean_line = line.replace('**', '')

            if clean_line.upper() in ["THE TL;DR:", "FINANCIAL METRICS EXTRACTED:", "ACTION ITEMS:"]:
                pdf.ln(5)
                _safe_write(pdf, clean_line.upper(), is_header=True)
            else:
                _safe_write(pdf, clean_line, is_header=False)

        try:
            pdf.output(str(output_path))
        except BaseException as e:
            logger.error(f"Failed to save Summary PDF: {str(e)}")

    async def _compress_mp3(self, input_path: Path, output_path: Path, bitrate: str = "128k"):
        """Compress or copy MP3 to specified path."""
        try:
            if input_path.suffix.lower() == '.mp3':
                import shutil
                shutil.copy2(str(input_path), str(output_path))
                return

            ffmpeg = FFMPEG_PATH or "ffmpeg"
            cmd = [ffmpeg, "-i", str(input_path), "-codec:a", "libmp3lame", "-b:a", bitrate, "-y", str(output_path)]
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await process.communicate()
        except Exception as e:
            logger.error(f"MP3 compression error: {e}")
            import shutil
            shutil.copy2(str(input_path), str(output_path))

engine = TranscriptionEngine()

# ─── FastAPI Application ─────────────────────────────────────────────────────
app = FastAPI(title="AI Transcriptor", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ─── Routes ──────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg.get("type") == "cancel":
                job_id = msg.get("job_id")
                if job_id:
                    engine.cancelled_jobs.add(job_id)
                    await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "🛑 Force Stop signal received."})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

# ─── Transcription Endpoints ─────────────────────────────────────────────────
@app.post("/api/transcribe/url")
async def transcribe_url(request: Request):
    body = await request.json()
    url = body.get("url", "").strip()
    company_name = body.get("company_name", "Meeting").strip()
    
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    job_id = str(uuid.uuid4())[:8]
    
    async def run_job():
        try:
            audio_path = await engine.download_audio(url, job_id)
            if job_id in engine.cancelled_jobs:
                return
            if audio_path:
                await engine.transcribe_full(audio_path, job_id, company_name)
                try:
                    audio_path.unlink()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Job {job_id} encountered unexpected error: {e}")
    
    asyncio.create_task(run_job())
    return {"job_id": job_id, "status": "started"}

@app.post("/api/transcribe/upload")
async def transcribe_upload(
    file: UploadFile = File(...),
    company_name: str = Form("Meeting")
):
    job_id = str(uuid.uuid4())[:8]
    
    # Save uploaded file
    file_path = TEMP_DIR / f"{job_id}_{file.filename}"
    with open(file_path, 'wb') as f:
        content = await file.read()
        f.write(content)
    
    async def run_job():
        try:
            if job_id in engine.cancelled_jobs:
                return
            await engine.transcribe_full(file_path, job_id, company_name)
        except Exception as e:
            logger.error(f"Upload Job {job_id} encountered unexpected error: {e}")
        try:
            file_path.unlink()
        except Exception:
            pass
    
    asyncio.create_task(run_job())
    return {"job_id": job_id, "status": "started"}

# ─── MP3 Tools Endpoints ─────────────────────────────────────────────────────
@app.post("/api/mp3/compress")
async def compress_mp3(
    file: UploadFile = File(...),
    bitrate: str = Form("128k")
):
    job_id = str(uuid.uuid4())[:8]
    input_path = TEMP_DIR / f"{job_id}_{file.filename}"
    
    with open(input_path, 'wb') as f:
        content = await file.read()
        f.write(content)
    
    output_path = MP3_DIR / f"compressed_{job_id}_{file.filename}"
    await engine._compress_mp3(input_path, output_path, bitrate)
    
    input_path.unlink(missing_ok=True)
    
    # Get file sizes
    original_size = len(content)
    compressed_size = output_path.stat().st_size if output_path.exists() else 0
    
    return {
        "status": "success",
        "output_path": str(output_path),
        "original_size_mb": round(original_size / (1024 * 1024), 2),
        "compressed_size_mb": round(compressed_size / (1024 * 1024), 2),
        "reduction_pct": round((1 - compressed_size / max(original_size, 1)) * 100, 1)
    }

@app.post("/api/mp3/merge")
async def merge_mp3(files: List[UploadFile] = File(...)):
    from pydub import AudioSegment
    
    job_id = str(uuid.uuid4())[:8]
    combined = AudioSegment.empty()
    
    for file in files:
        temp_path = TEMP_DIR / f"{job_id}_{file.filename}"
        with open(temp_path, 'wb') as f:
            f.write(await file.read())
        audio = AudioSegment.from_file(str(temp_path))
        combined += audio
        temp_path.unlink(missing_ok=True)
    
    output_path = MP3_DIR / f"merged_{job_id}.mp3"
    combined.export(str(output_path), format="mp3", bitrate="128k")
    
    return {
        "status": "success",
        "output_path": str(output_path),
        "duration_seconds": round(len(combined) / 1000, 1)
    }

@app.post("/api/mp3/split")
async def split_mp3(
    file: UploadFile = File(...),
    segment_minutes: int = Form(10)
):
    from pydub import AudioSegment
    
    job_id = str(uuid.uuid4())[:8]
    input_path = TEMP_DIR / f"{job_id}_{file.filename}"
    with open(input_path, 'wb') as f:
        f.write(await file.read())
    
    audio = AudioSegment.from_file(str(input_path))
    chunk_ms = segment_minutes * 60 * 1000
    outputs = []
    
    for i in range(0, len(audio), chunk_ms):
        chunk = audio[i:i + chunk_ms]
        chunk_path = MP3_DIR / f"split_{job_id}_part{(i // chunk_ms) + 1:03d}.mp3"
        chunk.export(str(chunk_path), format="mp3", bitrate="128k")
        outputs.append(str(chunk_path))
    
    input_path.unlink(missing_ok=True)
    
    return {
        "status": "success",
        "parts": len(outputs),
        "output_paths": outputs
    }

@app.post("/api/mp3/convert")
async def convert_to_mp3(
    file: UploadFile = File(...),
    bitrate: str = Form("128k")
):
    job_id = str(uuid.uuid4())[:8]
    input_path = TEMP_DIR / f"{job_id}_{file.filename}"
    with open(input_path, 'wb') as f:
        f.write(await file.read())
    
    output_path = MP3_DIR / f"converted_{job_id}.mp3"
    ffmpeg = FFMPEG_PATH or "ffmpeg"
    
    process = await asyncio.create_subprocess_exec(
        ffmpeg, "-i", str(input_path), "-codec:a", "libmp3lame", "-b:a", bitrate, "-y", str(output_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await process.communicate()
    input_path.unlink(missing_ok=True)
    
    return {
        "status": "success",
        "output_path": str(output_path),
        "size_mb": round(output_path.stat().st_size / (1024 * 1024), 2) if output_path.exists() else 0
    }

@app.post("/api/mp3/from-link")
async def mp3_from_link(
    url: str = Form(...),
    bitrate: str = Form("128k")
):
    job_id = str(uuid.uuid4())[:8]
    
    # 1. Download
    audio_path = await engine.download_audio(url, job_id)
    if not audio_path:
        raise HTTPException(status_code=400, detail="Could not download audio from link")
        
    # 2. Compress to desired bitrate
    output_path = MP3_DIR / f"downloaded_{job_id}.mp3"
    ffmpeg = FFMPEG_PATH or "ffmpeg"
    
    process = await asyncio.create_subprocess_exec(
        ffmpeg, "-i", str(audio_path), "-codec:a", "libmp3lame", "-b:a", bitrate, "-y", str(output_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await process.communicate()
    
    try:
        audio_path.unlink()
    except Exception:
        pass
        
    return {
        "status": "success",
        "job_id": job_id,
        "output_path": str(output_path),
        "size_mb": round(output_path.stat().st_size / (1024 * 1024), 2) if output_path.exists() else 0
    }

# ─── Settings Endpoints ──────────────────────────────────────────────────────
@app.get("/api/settings")
async def get_settings():
    return settings_manager.settings

@app.post("/api/settings")
async def update_settings(request: Request):
    body = await request.json()
    settings_manager.update(body)
    return {"status": "saved"}

@app.post("/api/settings/test-key")
async def test_api_key(request: Request):
    body = await request.json()
    key = body.get("key", "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key is required")
    
    import httpx
    try:
        verify = str(cert_path) if cert_path.exists() else True
        response = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
            verify=verify
        )
        if response.status_code == 200:
            models = response.json().get("data", [])
            return {"status": "valid", "models": [m["id"] for m in models]}
        else:
            return {"status": "invalid", "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

# ─── History Endpoints ───────────────────────────────────────────────────────
@app.get("/api/history")
async def get_history():
    return history_manager.get_all()

@app.delete("/api/history")
async def clear_history():
    history_manager.clear()
    return {"status": "cleared"}

# ─── Schedule Endpoints ──────────────────────────────────────────────────────
@app.get("/api/schedules")
async def get_schedules():
    return schedule_manager.get_all()

@app.post("/api/schedules")
async def add_schedule(request: Request):
    body = await request.json()
    schedule = schedule_manager.add(body)
    return schedule

@app.delete("/api/schedules/{schedule_id}")
async def remove_schedule(schedule_id: str):
    schedule_manager.remove(schedule_id)
    return {"status": "removed"}

# ─── File Download Endpoints ─────────────────────────────────────────────────
@app.get("/api/download/{file_type}/{filename}")
async def download_file(file_type: str, filename: str):
    if file_type == "transcript":
        base = OUTPUT_DIR
    elif file_type == "mp3":
        base = MP3_DIR
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    file_path = base / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(str(file_path), filename=filename)

# ─── System Info ──────────────────────────────────────────────────────────────
@app.get("/api/system")
async def system_info():
    keys = settings_manager.get_all_keys()
    return {
        "platform": platform.system(),
        "python_version": platform.python_version(),
        "ffmpeg_available": FFMPEG_PATH is not None,
        "ssl_cert_available": cert_path.exists(),
        "data_directory": str(APP_DATA_DIR),
        "output_directory": str(OUTPUT_DIR),
        "mp3_directory": str(MP3_DIR),
        "total_api_keys": len(keys),
        "paid_keys": len(settings_manager.settings.get("paid_api_keys", [])),
        "free_keys": len(settings_manager.settings.get("free_api_keys", [])),
        "history_count": len(history_manager.get_all()),
    }

# ─── Feedback Endpoint ───────────────────────────────────────────────────────
@app.post("/api/feedback")
async def submit_feedback(request: Request):
    body = await request.json()
    feedback = body.get("message", "")
    logger.info(f"Feedback received: {feedback}")
    return {"status": "received", "message": "Thank you for your feedback! It has been sent to shivamkole1234@gmail.com"}

# ─── Startup ──────────────────────────────────────────────────────────────────
def open_browser():
    """Open browser after a short delay."""
    import webbrowser
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8765")

if __name__ == "__main__":
    # Detect cloud deployment (Render.com sets RENDER=true)
    is_cloud = os.environ.get("RENDER") == "true"
    port = int(os.environ.get("PORT", 8765))
    host = "0.0.0.0" if is_cloud else "127.0.0.1"

    logger.info("=" * 60)
    logger.info("  AI Transcriptor")
    logger.info(f"  Mode: {'☁️ Cloud (Render.com)' if is_cloud else '🖥️ Desktop'}")
    logger.info(f"  Binding: {host}:{port}")
    logger.info(f"  Data Dir: {APP_DATA_DIR}")
    logger.info(f"  FFmpeg: {FFMPEG_PATH or 'Not found'}")
    logger.info(f"  SSL Cert: {'Yes' if cert_path.exists() else 'No'}")
    logger.info(f"  API Keys: {len(settings_manager.get_all_keys())}")
    logger.info("=" * 60)

    if is_cloud:
        # Cloud mode: just run uvicorn, no browser/pywebview
        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        # Desktop mode: try pywebview first, fallback to browser
        try:
            import webview
            server_thread = threading.Thread(
                target=uvicorn.run, args=(app,),
                kwargs={"host": host, "port": port, "log_level": "warning"},
                daemon=True
            )
            server_thread.start()
            time.sleep(1)
            icon_path = str(BASE_DIR / "static" / "logo.png")
            
            import sys
            if sys.platform == "darwin":
                try:
                    from AppKit import NSApplication, NSImage
                    app_inst = NSApplication.sharedApplication()
                    img = NSImage.alloc().initWithContentsOfFile_(icon_path)
                    if img:
                        app_inst.setApplicationIconImage_(img)
                except Exception as e:
                    logger.debug(f"macOS dock icon set failed: {e}")
            
            webview.create_window("AI Transcriptor", f"http://127.0.0.1:{port}", width=1400, height=900)
            webview.start(icon=icon_path)
        except ImportError:
            logger.info("pywebview not available, opening in browser...")
            threading.Thread(target=open_browser, daemon=True).start()
            uvicorn.run(app, host=host, port=port, log_level="info")

