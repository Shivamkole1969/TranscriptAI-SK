import requests
from main import settings_manager
from pathlib import Path

API_KEY = settings_manager.get_all_keys()[0] if settings_manager.get_all_keys() else 'none'
chunk_path = Path('./test_chunk.mp3')

files = {'file': ('test_chunk.mp3', open(chunk_path, 'rb'), 'audio/mpeg')}

long_prompt = (
    "Transcribe this corporate meeting audio with 100% word-for-word accuracy. "
    "Detect the English accent/dialect automatically and transcribe accordingly. Preserve regional terminology and financial terms: Lakh, Crore, EBITDA. "
    "CRITICAL KEYWORDS TO SPELL CORRECTLY: Mukesh Ambani, Reliance Industries, Jio, Retail, Telecom, O2C, New Energy, Green Energy, Dhirubhai Ambani, 48th AGM, FY25, Q1, EBITDA, Profit, Growth, Dividend, 5G, Broadband, Fiber, Hydrogen, Solar, Battery, Carbon Neutral, 2035, Future, Investment, Vision, India, Global, Leadership, Innovation, Sustainability, Digital, Commerce, Ecosystem, Partnerships, Technology, Transformation, Scale, Excellence. "
    "Preserve financial terms: Lakh, Crore, EBITDA, Revenue, Margin, YoY, QoQ, "
    "CAGR, PAT, PBT, EPS, P/E, ROE, ROA, ROCE, Capex, Opex, NPA, AUM, NAV. "
    "Identify and label different speakers as Speaker 1, Speaker 2, etc. "
    "Mark speaker changes clearly. Do not skip or summarize any content."
)

data = {
    'model': 'whisper-large-v3',
    'language': 'en',
    'response_format': 'verbose_json',
    'prompt': long_prompt
}

response = requests.post(
    'https://api.groq.com/openai/v1/audio/transcriptions',
    headers={'Authorization': f'Bearer {API_KEY}'},
    files=files,
    data=data
)

print(response.status_code)
print(response.text)
