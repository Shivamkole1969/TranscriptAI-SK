# AI Transcriptor - Ultimate Build Prompt

*Copy and paste the below block into any advanced AI (like Claude 3.5 Sonnet, GPT-4, or Gemini 1.5 Pro) on a completely new machine to recreate the entire application from scratch.*

---
---

**PROMPT TO REBUILD ENTIRE APPLICATION:**

"I want to build an extremely robust, high-performance 'AI Transcriptor' application for a corporate Data Analyst workflow. It needs to have a sleek, modern, dark-themed UI. Below are the EXACT specifications of the architecture, features, styling, and structural rules. Please build everything from the ground up, including the Python backend (FastAPI), the HTML/JS/CSS frontend, and the PyInstaller setup.

### 1. Core Architecture & Tech Stack:
*   **Backend:** Python 3.10+, FastAPI for endpoints, `uvicorn` for running it.
*   **Frontend HTML/CSS/JS:** Vanilla HTML/JavaScript, Jinja2 Templates, and Custom CSS (Sleek dark mode: `#0f172a` primary background, nice box shadows, and vibrant standard blues for buttons).
*   **Desktop Wrapper:** `pywebview` window to wrap the FastAPI server so it looks like a native Desktop application.
*   **Transcription Engine:** GROQ API natively using `whisper-large-v3`.
*   **YouTube/Video Downloader:** `yt-dlp` paired with `imageio-ffmpeg` and `subprocess` to directly extract `.mp3`.
*   **PDF Generation:** `fpdf2` (or `fpdf`) to generate professional transcripts.
*   **Audio Splitting:** `pydub` (with access to local `ffmpeg.exe`) to split huge audio into chunks of 10-minutes.

### 2. Required Features:
*   **Multi-Key Parallelism:** The app must be able to load multiple Groq API keys (e.g., 8 keys) from a local JSON file (`%LOCALAPPDATA%/AITranscriptor/api_settings.json`). When checking chunks, it must use Python's `ThreadPoolExecutor` or `asyncio` to blast 20-40 chunks of audio in parallel across all available keys (Round-Robin logic).
*   **Word-for-Word Transcription:** The Whisper prompt MUST be set to require 100% word-for-word accuracy, specifically configured for 'Elite Financial Analyst' mode, preserving words like 'Lakh', 'Crore', 'EBITDA', etc.
*   **Speaker Diarization Regex:** Force Whisper to identify speakers. Add a post-processor Regex that forces `Speaker X:` tags onto new lines with double spacing to avoid 'wall of text' output.
*   **Real-Time Processing UI (Queue):** The web interface uses WebSockets to show an 'Active Queue'. Each job must show a progress bar (0 to 100%), and a live log (e.g., 'Processed chunk 7/9...', 'Downloading audio...'). No dancing or jittering CSS animations.
*   **Isolated Data:** The tool will be shared on OneDrive, meaning `main.py` CANNOT store logs, API keys, or history in the same folder. Instead, use `os.environ.get('LOCALAPPDATA')` to create a `AITranscriptor` folder on the local user's C: drive. All `history.json` and `api_settings.json` must be stored here so 20 people can use the exact same folder independently.
*   **PDF Output:** PDFs must contain a header with the "Company Name - TRANSCRIPT", and flush right must contain the Date of transcription and the 'Total Processing Time' it took to generate.

### 3. Corporate Security / Offline Constraints:
*   Do NOT rely on system-wide FFmpeg. The app must assume `ffmpeg.exe` sits next to `main.py` and actively map `os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path` and configure `AudioSegment.converter`.
*   Assume the user is behind a strict Zscaler Firewall. Implement SSL certificate bypass by looking for `custom_bundle.pem` next to `main.py` and forcibly setting `os.environ['CURL_CA_BUNDLE'] = cert_path`.

### 4. Build Scripts & Deployment:
*   Provide a complete `BUILD_WINDOWS_EXE.bat` script that uses PyInstaller.
*   The PyInstaller script MUST use `--onedir` (not `--onefile`), include `--hidden-import "uvicorn"`, `--hidden-import "fastapi"`, and copy `templates` and `static`.
*   Provide a failsafe path resolver in `main.py`: Use `sys._MEIPASS \ "_internal"` to reliably locate `static` and `templates` when frozen. If they don't exist, create an empty `templates` folder via `os.makedirs` so it never crashes hard.
*   Provide a `START_APP.bat` script that simply runs `python main.py` as a fallback.

### What to output:
1. `requirements.txt`
2. Full `main.py` (with FastAPI, WebSocket queue, Groq parallelism, fallback logic, PDF gen, user LocalAppData mapping, and Zscaler integration).
3. `templates/index.html` (Full beautiful UI, Sharp, clean and very High definition, 3D effect in background like calm water flowing layout).
4. `static/css/style.css` (Dark/light mode design).
5. `static/js/app.js` (WebSocket listener, form submitter, and UI progress manager).
6. `BUILD_WINDOWS_EXE.bat`.

Please generate these artifacts to perfection."
