import asyncio
import os
from pathlib import Path

# Adjust import path if needed
import sys
sys.path.append(str(Path(__file__).parent))

from main import TranscriptAI

async def test_download():
    # Use a short public YouTube video URL (e.g., a test video)
    url = "https://www.youtube.com/watch?v=2Vv-BfVoq4g"  # Ed Sheeran - Shape of You (short clip)
    job_id = "test123"
    # Create a dummy settings manager if needed (main uses SettingsManager)
    # We'll instantiate TranscriptAI which sets up settings_manager internally.
    ai = TranscriptAI()
    # Directly call download_audio (it's an async method)
    result = await ai.download_audio(url, job_id)
    print("Download result:", result)

if __name__ == "__main__":
    asyncio.run(test_download())
