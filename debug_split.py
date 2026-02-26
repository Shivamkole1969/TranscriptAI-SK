import asyncio
from pathlib import Path
from main import TranscriptionEngine

async def test():
    engine = TranscriptionEngine()
    audio_path = Path("/Users/shivam.kole/Library/Application Support/AITranscriptor/temp/6b9667cd.mp3")
    print("Starting split_audio task...")
    
    loop = asyncio.get_event_loop()
    chunks = await loop.run_in_executor(None, engine.split_audio, audio_path, 10)
    print("Finished split audio!", len(chunks))

asyncio.run(test())
