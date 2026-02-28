import os
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

# Audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
AUDIO_DTYPE = "int16"
CHUNK_DURATION_MS = 100

# Deepgram settings
DEEPGRAM_MODEL = "nova-3"
DEEPGRAM_LANGUAGE = "ru"
DEEPGRAM_ENCODING = "linear16"
DEEPGRAM_ENDPOINTING = 300

# LLM settings
LLM_MODEL_FAST = "gpt-4o-mini"
LLM_MODEL_QUALITY = "gpt-4o"
LLM_MAX_TOKENS = 2048
LLM_TEMPERATURE = 0.3

# Server settings
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8765

# Context settings
MAX_CONTEXT_TOKENS = 6000
MAX_RECENT_EXCHANGES = 5
