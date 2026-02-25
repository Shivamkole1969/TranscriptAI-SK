import os
import sys
import time
import subprocess
from pathlib import Path

# --- Auto-Install Dependencies ---
def ensure_dependencies():
    try:
        import yt_dlp
        import requests
    except ImportError:
        print("📦 Installing required packages (yt-dlp, requests)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp", "requests", "--quiet"])
        print("✅ Packages installed successfully!\n")

ensure_dependencies()

import yt_dlp
import requests

# --- Configuration ---
HF_SPACE_URL = "https://shivamkole1969-transcriptai-sk.hf.space"
UPLOAD_URL = f"{HF_SPACE_URL}/api/transcribe/upload"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    clear_screen()
    print("=" * 60)
    print(" 🤖 AI Transcriptor - Local Fetch Agent ".center(60, " "))
    print("=" * 60)
    print("\nThis tool bypasses YouTube Cloud Datacenter Blocks by downloading")
    print("the audio on your local computer, then seamlessly uploading it")
    print("to your Cloud Dashboard for AI Transcription.\n")
    
    url = input("🔗 Enter YouTube / Video URL: ").strip()
    if not url:
        return
        
    company = input("🏢 Enter Meeting/Company Name (Optional): ").strip()
    if not company:
        company = "Meeting"
        
    print("\n📥 Step 1: Downloading audio locally (bypassing blocks)...")
    
    # Secure a temp filename
    temp_file = "local_agent_temp_audio"
    
    # Keep it simple, let yt-dlp grab the best audio, no ffmpeg required locally if we don't convert
    ydl_opts = {
        'format': 'm4a/bestaudio/best',
        'outtmpl': temp_file + '.%(ext)s',
        'quiet': False,
        'no_warnings': True,
    }
    
    downloaded_file = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = info.get('ext', 'm4a')
            downloaded_file = f"{temp_file}.{ext}"
    except Exception as e:
        print(f"\n❌ Error downloading: {e}")
        input("Press Enter to exit...")
        return
        
    if not os.path.exists(downloaded_file):
        # Fallback if FFmpeg isn't installed locally (yt-dlp downloads m4a/webm)
        for f in os.listdir("."):
            if f.startswith(temp_file):
                downloaded_file = f
                break
                
    if not os.path.exists(downloaded_file):
        print("\n❌ Could not find downloaded file. Do you have FFmpeg installed?")
        input("Press Enter to exit...")
        return
        
    print(f"\n✅ Download complete. Selected file: {downloaded_file}")
    print(f"☁️  Step 2: Uploading to {HF_SPACE_URL} ...")
    
    try:
        with open(downloaded_file, 'rb') as f:
            files = {'file': (downloaded_file, f, 'audio/mpeg')}
            data = {'company_name': company}
            
            response = requests.post(UPLOAD_URL, files=files, data=data)
            
        if response.status_code == 200:
            job_info = response.json()
            job_id = job_info.get("job_id", "")
            print("\n" + "=" * 60)
            print("🎉 UPLOAD SUCCESSFUL!")
            print(f"Task ID: {job_id}")
            print(f"Open your dashboard to monitor the transcription:")
            print(f"👉 {HF_SPACE_URL}")
            print("=" * 60 + "\n")
        else:
            print(f"\n❌ Server rejected the upload. Status Code: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"\n❌ Error uploading: {e}")
        
    finally:
        # Cleanup
        try:
            if os.path.exists(downloaded_file):
                os.remove(downloaded_file)
        except:
            pass
            
    input("Press Enter to exit...")

if __name__ == "__main__":
    main()
