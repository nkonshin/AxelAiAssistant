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

# LLM settings — defaults (can be changed at runtime via /settings)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # "openai" or "claude"
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_MAX_TOKENS = 2048
LLM_TEMPERATURE = 0.3

# CLIProxyAPI settings (for Claude via Max subscription)
CLI_PROXY_URL = os.getenv("CLI_PROXY_URL", "http://localhost:8317/v1")
CLI_PROXY_API_KEY = os.getenv("CLI_PROXY_API_KEY", "your-api-key-1")  # Must match api-keys in cliproxyapi.conf

# Available models per provider
OPENAI_MODELS = ["gpt-4o-mini", "gpt-5-mini", "gpt-5-nano"]
CLAUDE_MODELS = ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"]
CLAUDE_MODEL_LABELS = {
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-opus-4-6": "Opus 4.6",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
}

# Server settings
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8765

# Context settings
MAX_CONTEXT_TOKENS = 6000
MAX_RECENT_EXCHANGES = 5
