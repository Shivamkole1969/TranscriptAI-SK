import requests
from main import settings_manager
from pathlib import Path

API_KEY = settings_manager.get_all_keys()[0] if settings_manager.get_all_keys() else 'none'
chunk_path = Path('./test_chunk.mp3')

files = {'file': ('test_chunk.mp3', open(chunk_path, 'rb'), 'audio/mpeg')}
data = {
    'model': 'whisper-large-v3',
    'language': 'en',
    'response_format': 'verbose_json',
    'prompt': 'Transcribe this corporate meeting audio with 100% word-for-word accuracy.'
}

response = requests.post(
    'https://api.groq.com/openai/v1/audio/transcriptions',
    headers={'Authorization': f'Bearer {API_KEY}'},
    files=files,
    data=data
)

print(response.status_code)
print(response.text)
