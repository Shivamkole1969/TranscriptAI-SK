#!/usr/bin/env python3
"""
AI Transcriptor by Shivam Kole
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
            "chunk_duration_minutes": 10,
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
        self.key_usage = defaultdict(lambda: {"calls": 0, "last_reset": time.time()})
        self.key_lock = threading.Lock()
        self.active_jobs: Dict[str, dict] = {}

    def _get_next_key(self, keys: list) -> Optional[str]:
        """Round-robin key selection with rate limit awareness."""
        if not keys:
            return None
        with self.key_lock:
            now = time.time()
            best_key = None
            min_calls = float('inf')
            for key in keys:
                usage = self.key_usage[key]
                if now - usage["last_reset"] > 60:
                    usage["calls"] = 0
                    usage["last_reset"] = now
                if usage["calls"] < min_calls:
                    min_calls = usage["calls"]
                    best_key = key
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

    async def _download_via_rapidapi(self, video_id: str, job_id: str, api_key: str) -> Optional[Path]:
        """Download using a free RapidAPI (youtube-mp36) to bypass all IP blocks."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                headers = {
                    "x-rapidapi-key": api_key,
                    "x-rapidapi-host": "youtube-mp36.p.rapidapi.com"
                }
                resp = await client.get(f"https://youtube-mp36.p.rapidapi.com/dl?id={video_id}", headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"RapidAPI returned {resp.status_code}: {resp.text}")
                    return None
                    
                data = resp.json()
                dl_url = data.get("link")
                
                # Some APIs take a moment to process the mp3
                if not dl_url and data.get("msg") == "in progress":
                    for _ in range(15):
                        await asyncio.sleep(2)
                        resp = await client.get(f"https://youtube-mp36.p.rapidapi.com/dl?id={video_id}", headers=headers)
                        if resp.status_code == 200:
                            data = resp.json()
                            if data.get("link"):
                                dl_url = data.get("link")
                                break
                                
                if dl_url:
                    await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"⬇️ Downloading MP3 via RapidAPI..."})
                    audio_resp = await client.get(dl_url, timeout=120, follow_redirects=True)
                    if audio_resp.status_code == 200 and len(audio_resp.content) > 10000:
                        mp3_path = TEMP_DIR / f"{job_id}.mp3"
                        mp3_path.write_bytes(audio_resp.content)
                        await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": f"✅ Audio downloaded via RapidAPI!"})
                        return mp3_path
        except Exception as e:
            logger.warning(f"RapidAPI failed: {e}")
        return None

    async def download_audio(self, url: str, job_id: str) -> Optional[Path]:
        """Download audio from URL using robust multi-backend approach.
        
        Strategy for YouTube on cloud:
        1. RapidAPI (if key provided in settings - 100% reliable)
        2. Invidious/Piped proxy APIs (bypasses ALL datacenter IP blocks)
        3. pytubefix (direct API, sometimes works)
        4. yt-dlp with cookies (last resort)
        """
        await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "📥 Downloading audio from URL..."})
        
        is_youtube = "youtube.com" in url.lower() or "youtu.be" in url.lower()
        is_cloud = os.environ.get("RENDER") == "true" or os.environ.get("SPACE_ID") is not None
        
        # ═══ 1. RAPIDAPI (If provided, bypasses all blocks) ═══
        if is_youtube:
            rapidapi_key = settings_manager.settings.get("rapidapi_key", "").strip()
            if rapidapi_key:
                video_id = self._extract_video_id(url)
                if video_id:
                    await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "🚀 Using RapidAPI for guaranteed YouTube bypass..."})
                    result = await self._download_via_rapidapi(video_id, job_id, rapidapi_key)
                    if result:
                        return result
                    await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "⚠️ RapidAPI failed or quota exceeded, continuing to fallback methods..."})

        # ═══ 2. CLOUD YOUTUBE: Public Proxies ═══
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
        """Split audio into chunks using pydub."""
        from pydub import AudioSegment
        
        audio = AudioSegment.from_file(str(audio_path))
        chunk_ms = chunk_minutes * 60 * 1000
        chunks = []
        
        for i in range(0, len(audio), chunk_ms):
            chunk = audio[i:i + chunk_ms]
            chunk_path = TEMP_DIR / f"{audio_path.stem}_chunk_{i // chunk_ms:04d}.mp3"
            chunk.export(str(chunk_path), format="mp3", bitrate="128k")
            chunks.append(chunk_path)
        
        return chunks

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
                        {"role": "user", "content": f"I am about to transcribe a business meeting/call titled '{company_name}'. Generate EXACTLY 30 to 40 highly specific keywords. Specifically include: up to 10 names of key chairpersons/executives/important people associated with this company, major product names, subsidiary entities, relevant places, and key financial/technical terms related to this context. Only give the comma-separated words so I can feed them to Whisper."}
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

    def transcribe_chunk(self, chunk_path: Path, api_key: str, model: str = "whisper-large-v3", context_keywords: str = "") -> dict:
        """Transcribe a single audio chunk using Groq API."""
        import httpx
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                with open(chunk_path, 'rb') as f:
                    files = {'file': (chunk_path.name, f, 'audio/mpeg')}
                    # Build dialect-aware prompt
                    dialect = settings_manager.settings.get("english_dialect", "indian")
                    dialect_prompts = {
                        "indian": (
                            "The speakers use Indian English accents and pronunciations. "
                            "Preserve Indian financial terms: Lakh, Crore, Rupees, Paise. "
                            "Common Indian English words: prepone, revert, updation, do the needful. "
                        ),
                        "british": (
                            "The speakers use British English accents and pronunciations. "
                            "Use British spelling: organisation, colour, behaviour, analyse, programme. "
                        ),
                        "american": (
                            "The speakers use American English accents and pronunciations. "
                            "Use American spelling: organization, color, behavior, analyze, program. "
                        ),
                        "australian": (
                            "The speakers use Australian English accents and pronunciations. "
                            "Use Australian/British spelling conventions. "
                        ),
                        "mixed": (
                            "The speakers may use different English accents (Indian, British, American, etc). "
                            "Preserve each speaker's natural terminology and phrasing accurately. "
                            "Preserve Indian financial terms: Lakh, Crore, Rupees, Paise. "
                        ),
                        "auto": (
                            "Detect the English accent/dialect automatically and transcribe accordingly. "
                            "Preserve regional terminology and financial terms: Lakh, Crore, EBITDA. "
                        )
                    }
                    dialect_hint = dialect_prompts.get(dialect, dialect_prompts["auto"])
                    
                    # Inject contextual keywords if generated by the AI
                    keyword_injection = f"CRITICAL KEYWORDS TO SPELL CORRECTLY: {context_keywords}. " if context_keywords else ""
                    
                    data = {
                        'model': model,
                        'language': 'en',
                        'response_format': 'verbose_json',
                        'prompt': (
                            "Transcribe this corporate meeting audio with 100% word-for-word accuracy. "
                            f"{dialect_hint}"
                            f"{keyword_injection}"
                            "Preserve financial terms: Lakh, Crore, EBITDA, Revenue, Margin, YoY, QoQ, "
                            "CAGR, PAT, PBT, EPS, P/E, ROE, ROA, ROCE, Capex, Opex, NPA, AUM, NAV. "
                            "Identify and label different speakers as Speaker 1, Speaker 2, etc. "
                            "Mark speaker changes clearly. Do not skip or summarize any content."
                        )
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
                        retry_after = int(response.headers.get('retry-after', 30))
                        logger.warning(f"Rate limited, waiting {retry_after}s...")
                        time.sleep(retry_after)
                        continue
                    
                    response.raise_for_status()
                    return response.json()
                    
            except Exception as e:
                logger.error(f"Chunk transcription error (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))
                else:
                    return {"text": f"[ERROR: Could not transcribe chunk - {str(e)}]", "error": True}
        
        return {"text": "[ERROR: Max retries exceeded]", "error": True}

    def post_process_transcript(self, text: str) -> str:
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
        return text.strip()

    async def transcribe_full(self, audio_path: Path, job_id: str, company_name: str = "Meeting") -> dict:
        """Full transcription pipeline with parallel chunk processing."""
        start_time = time.time()
        all_keys = settings_manager.get_all_keys()
        
        if not all_keys:
            await ws_manager.broadcast({"type": "error", "job_id": job_id, "message": "❌ No API keys configured! Go to Settings → API Keys to add your Groq keys."})
            return {"error": "No API keys configured"}

        model = settings_manager.settings.get("default_model", "whisper-large-v3")
        chunk_minutes = settings_manager.settings.get("chunk_duration_minutes", 10)
        max_workers = min(settings_manager.settings.get("max_parallel_workers", 20), len(all_keys) * 3)

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
        completed = [0]

        def process_chunk(idx, chunk_path):
            key = self._get_next_key(all_keys)
            if not key:
                return idx, {"text": "[ERROR: No API key available]", "error": True}
            result = self.transcribe_chunk(chunk_path, key, model, keywords)
            completed[0] += 1
            return idx, result

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, chunk in enumerate(chunks):
                futures.append(executor.submit(process_chunk, i, chunk))
            
            for future in futures:
                idx, result = future.result()
                results[idx] = result
                progress = int(5 + (completed[0] / total_chunks) * 85)
                asyncio.run_coroutine_threadsafe(
                    ws_manager.broadcast({
                        "type": "progress", "job_id": job_id,
                        "progress": progress,
                        "message": f"🔄 Processed chunk {completed[0]}/{total_chunks}..."
                    }),
                    loop
                )

        # Combine results
        await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "📝 Combining and formatting transcript..."})
        
        full_text = ""
        errors = []
        for i, result in enumerate(results):
            if result and not result.get("error"):
                text = result.get("text", "")
                full_text += f"\n\n--- Segment {i+1} ---\n\n{text}"
            else:
                errors.append(f"Chunk {i+1}: {result.get('text', 'Unknown error')}")

        # Post-process
        full_text = self.post_process_transcript(full_text)
        
        processing_time = time.time() - start_time
        
        # Generate outputs
        await ws_manager.broadcast({"type": "log", "job_id": job_id, "message": "📄 Generating files & building master bundle..."})
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        safe_name = re.sub(r'[^\w\s-]', '', company_name).strip().replace(' ', '_')
        file_prefix = f"{safe_name}_{timestamp}"
        
        # Save TXT
        txt_path = OUTPUT_DIR / f"{file_prefix}.txt"
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(f"{company_name} - TRANSCRIPT\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"Processing Time: {processing_time:.1f} seconds\n")
            f.write("=" * 60 + "\n\n")
            f.write(full_text)

        # Save PDF
        pdf_path = OUTPUT_DIR / f"{file_prefix}.pdf"
        self._generate_pdf(pdf_path, company_name, full_text, processing_time)

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
                self.cell(0, 6, f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M")} | Processing Time: {processing_time:.1f}s', ln=True, align='R')
                self.line(10, self.get_y(), 200, self.get_y())
                self.ln(5)

            def footer(self):
                self.set_y(-15)
                self.set_font('Helvetica', 'I', 8)
                self.cell(0, 10, f'AI Transcriptor by Shivam Kole | Page {self.page_no()}/{{nb}}', align='C')

        pdf = TranscriptPDF()
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_font('Helvetica', '', 10)

        for line in text.split('\n'):
            line = line.strip()
            if not line:
                pdf.ln(3)
                continue
            if re.match(r'Speaker\s*\d+\s*:', line):
                pdf.set_font('Helvetica', 'B', 10)
                pdf.multi_cell(0, 5, line.encode('latin-1', 'replace').decode('latin-1'))
                pdf.set_font('Helvetica', '', 10)
            elif line.startswith('---'):
                pdf.set_font('Helvetica', 'I', 9)
                pdf.cell(0, 5, line, ln=True)
                pdf.set_font('Helvetica', '', 10)
            else:
                pdf.multi_cell(0, 5, line.encode('latin-1', 'replace').decode('latin-1'))

        pdf.output(str(output_path))

    async def _compress_mp3(self, input_path: Path, output_path: Path, bitrate: str = "128k"):
        """Compress MP3 to specified bitrate."""
        ffmpeg = FFMPEG_PATH or "ffmpeg"
        cmd = [ffmpeg, "-i", str(input_path), "-codec:a", "libmp3lame", "-b:a", bitrate, "-y", str(output_path)]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
        except Exception as e:
            logger.error(f"MP3 compression error: {e}")
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
        audio_path = await engine.download_audio(url, job_id)
        if audio_path:
            await engine.transcribe_full(audio_path, job_id, company_name)
            try:
                audio_path.unlink()
            except Exception:
                pass
    
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
        await engine.transcribe_full(file_path, job_id, company_name)
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
    logger.info("  AI Transcriptor by Shivam Kole")
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
            webview.create_window("AI Transcriptor by Shivam Kole", f"http://127.0.0.1:{port}", width=1400, height=900)
            webview.start(icon=icon_path)
        except ImportError:
            logger.info("pywebview not available, opening in browser...")
            threading.Thread(target=open_browser, daemon=True).start()
            uvicorn.run(app, host=host, port=port, log_level="info")

