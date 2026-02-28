# Axel AI Assistant

Real-time AI interview assistant for macOS. Listens to the interview audio (microphone + interviewer voice from Zoom/Teams/Meet), transcribes speech, detects questions, and generates answers in an invisible overlay on top of your screen.

## Architecture

```
┌─────────────────────────────────────────┐
│          Electron Overlay (React)        │
│  Transparent, always-on-top, stealth    │
│  Content protection (hidden from share) │
└──────────┬────────────────┬─────────────┘
           │ SSE            │ HTTP
           ▼                ▼
┌─────────────────────────────────────────┐
│          Python Backend (FastAPI)         │
│  Audio Capture → Deepgram → GPT-4o      │
│  Question Detection → Streaming Answer  │
└─────────────────────────────────────────┘
```

## Prerequisites

- macOS 13+
- Python 3.11+
- Node.js 18+
- [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole) (virtual audio driver)
- portaudio

```bash
brew install blackhole-2ch portaudio node
```

## BlackHole Setup (required)

1. Open **Audio MIDI Setup** (Spotlight → "Audio MIDI Setup")
2. Click **"+"** → **Create Multi-Output Device**
3. Check: **Built-in Output** + **BlackHole 2ch**
4. Right-click → **Use This Device For Sound Output**
5. Verify: audio plays normally through speakers

## Installation

```bash
# Clone the repo
git clone https://github.com/nkonshin/AxelAiAssistant.git
cd AxelAiAssistant

# Create .env with your API keys
cp .env.example .env
# Edit .env and add your keys

# Run setup (installs all dependencies)
./scripts/setup.sh
```

## Usage

```bash
# Start everything (backend + overlay)
./scripts/dev.sh
```

Or run manually:

```bash
# Terminal 1: Python backend
cd backend && source .venv/bin/activate && python main.py

# Terminal 2: Electron overlay
cd overlay && npm run dev
```

## Hotkeys

| Shortcut | Action |
|---|---|
| `Cmd+Shift+\` | Show / hide overlay |
| `Cmd+Shift+M` | Start / stop recording |
| `Cmd+Shift+A` | Force answer generation |
| `Cmd+Shift+S` | Screenshot → AI analysis |
| `Cmd+Shift+C` | Copy last answer |
| `Cmd+Shift+↑` | Increase opacity |
| `Cmd+Shift+↓` | Decrease opacity |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/stream` | SSE event stream |
| GET | `/status` | App state |
| GET | `/transcript` | Full transcript |
| POST | `/start` | Start recording |
| POST | `/stop` | Stop recording |
| POST | `/screenshot` | Capture + analyze screen |
| POST | `/force-answer` | Force answer from buffer |

## Tech Stack

- **Backend**: Python, FastAPI, sounddevice, Deepgram Nova-3, OpenAI GPT-4o
- **Frontend**: Electron, React, TypeScript, Tailwind CSS
- **Audio**: BlackHole 2ch for system audio capture

## Troubleshooting

**No sound from BlackHole**: Make sure Multi-Output Device is set as default output in System Settings → Sound.

**"BlackHole not found" error**: Install with `brew install blackhole-2ch` and restart.

**Overlay visible in screen share**: Verify `setContentProtection(true)` is active. On macOS 15+ some apps use ScreenCaptureKit which may bypass protection.

**Missing API keys**: Create `.env` from `.env.example` and add your OpenAI and Deepgram keys.

## License

MIT
