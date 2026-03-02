# Axel AI Assistant

Real-time AI interview assistant for macOS. Listens to the interview audio (microphone + interviewer voice from Zoom/Teams/Meet), transcribes speech in real time, automatically detects questions, and generates answers in an invisible overlay on top of your screen.

## Features

- **Stealth overlay** — invisible to screen sharing (content protection), always on top, transparent
- **Dual audio capture** — microphone (candidate) + system audio (interviewer via BlackHole)
- **Real-time transcription** — local Whisper (whisper.cpp) or cloud Deepgram Nova-3
- **Auto question detection** — 3s pause after interviewer speech triggers answer generation
- **Streaming AI answers** — GPT-4o / Claude with markdown rendering and code highlighting
- **Screenshot analysis** — capture screen and send to Vision model for code/task analysis
- **Separate mic buffer** — candidate's mic doesn't auto-trigger; manual send via F5
- **Chat-style answer view** — scrollable history of all Q&A pairs with auto-scroll
- **Runtime settings** — switch LLM provider/model, transcription provider, upload resume/job description

## Architecture

```
┌──────────────────────────────────────────────────┐
│            Electron Overlay (React + TS)          │
│  Transparent, frameless, always-on-top           │
│  setContentProtection(true) — hidden from share  │
│  Dynamic size: 60% width centered, 80% opacity   │
└──────────┬─────────────────────┬─────────────────┘
           │ SSE (answers,       │ HTTP (commands,
           │  transcripts)       │  settings)
           ▼                     ▼
┌──────────────────────────────────────────────────┐
│            Python Backend (FastAPI)               │
│                                                   │
│  Audio Capture ──→ Whisper/Deepgram ──→ Question │
│  (sounddevice)     (transcription)     Detector  │
│                                           │      │
│  Screenshot ──→ Vision Model              ▼      │
│  (Pillow)       (GPT-4o)          LLM Streaming  │
│                                   (GPT-4o/Claude)│
│                                        │         │
│  Context Manager ◄────────────────────►│         │
│  (conversation history)          SSE → Overlay   │
└──────────────────────────────────────────────────┘
```

## Prerequisites

- macOS 13+
- Python 3.11+
- Node.js 18+
- [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole) — virtual audio driver for system sound capture
- portaudio — audio backend for sounddevice

```bash
brew install blackhole-2ch portaudio node
```

## BlackHole Setup (required for interviewer audio)

1. Open **Audio MIDI Setup** (Spotlight → "Audio MIDI Setup")
2. Click **"+"** → **Create Multi-Output Device**
3. Check: **Built-in Output** + **BlackHole 2ch**
4. Right-click → **Use This Device For Sound Output**
5. Verify: audio plays normally through speakers

> Without BlackHole the app still works in mic-only mode — it captures your microphone and you trigger answers manually with F5.

## Installation

```bash
# Clone the repo
git clone https://github.com/nkonshin/AxelAiAssistant.git
cd AxelAiAssistant

# Create .env with your API keys
cp .env.example .env
# Edit .env and add your keys

# Run setup (installs Python venv, npm packages, downloads Whisper model)
./scripts/setup.sh
```

### Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...          # OpenAI API key

# Optional — Deepgram (only if using cloud transcription)
DEEPGRAM_API_KEY=...           # Deepgram API key

# Optional — Claude via CLIProxyAPI (Max subscription)
CLI_PROXY_URL=http://localhost:8317/v1
CLI_PROXY_API_KEY=your-api-key-1

# Transcription (default: whisper)
TRANSCRIPTION_PROVIDER=whisper  # "whisper" or "deepgram"
WHISPER_MODEL=large-v3-turbo    # tiny, base, small, medium, large-v3, large-v3-turbo

# LLM (default: openai / gpt-4o-mini)
LLM_PROVIDER=openai             # "openai" or "claude"
LLM_MODEL=gpt-4o-mini
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

### Background Launch (no terminal window)

```bash
# Option A: nohup (close terminal after)
nohup /path/to/AxelAiAssistant/scripts/dev.sh > /dev/null 2>&1 &

# Option B: AppleScript launcher (in ~/Documents/AxelAssistant.app)
# Double-click to launch, no terminal window at all
```

Stop background processes:
```bash
pkill -f "python3 main.py"; pkill -f "electron-vite"
```

## Hotkeys

| Shortcut | Action |
|---|---|
| `Cmd+Shift+\` | Show / hide overlay |
| `Cmd+Shift+M` | Start / stop recording |
| `Cmd+Shift+A` | Force answer (send all buffers to LLM) |
| `F5` | Send mic buffer to LLM (candidate's speech) |
| `Cmd+Shift+S` | Screenshot → AI Vision analysis |
| `Cmd+Shift+C` | Copy last answer to clipboard |
| `Cmd+Shift+I` | Toggle manual input bar |
| `Cmd+Shift+T` | Toggle click-through mode |
| `Cmd+Shift+↑` | Increase opacity |
| `Cmd+Shift+↓` | Decrease opacity |

## How It Works

1. **Start recording** (`Cmd+Shift+M`) — captures mic + system audio simultaneously
2. **Interviewer speaks** — system audio (BlackHole) is transcribed and buffered
3. **3s pause detected** — auto-triggers LLM to generate an answer
4. **Answer streams** into the overlay with markdown rendering
5. **You speak** — mic audio is transcribed but does NOT auto-trigger (prevents echo-answers)
6. **F5 to send mic** — manually sends your speech buffer to LLM if needed
7. **Screenshot** (`Cmd+Shift+S`) — captures screen for code/task analysis via Vision model

## LLM Providers

| Provider | Models | Setup |
|---|---|---|
| **OpenAI** | gpt-4o-mini, gpt-5-mini, gpt-5-nano | `OPENAI_API_KEY` in `.env` |
| **Claude** | claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5 | [CLIProxyAPI](https://github.com/nickconshin/cliproxyapi) + Claude Max subscription |

Switch providers at runtime via Settings panel in the overlay.

## Transcription Providers

| Provider | How | Pros / Cons |
|---|---|---|
| **Whisper** (default) | Local, pywhispercpp (whisper.cpp + Metal GPU) | No API key needed, private. ~0.5s inference per chunk |
| **Deepgram** | Cloud, Nova-3 WebSocket streaming | Lower latency, requires API key |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/stream` | SSE event stream (transcripts, answers, status) |
| GET | `/status` | Current app state |
| GET | `/transcript` | Full transcript log |
| POST | `/start` | Start audio capture + transcription |
| POST | `/stop` | Stop recording |
| POST | `/screenshot` | Capture screen → Vision AI analysis |
| POST | `/force-answer` | Force answer from all buffers |
| POST | `/trigger-mic` | Send mic buffer to LLM (F5) |
| POST | `/ask` | Submit manual text question |
| GET/POST | `/settings/llm` | Get/set LLM provider and model |
| GET/POST | `/settings/transcription` | Get/set transcription provider and model |
| GET/POST | `/settings/profile` | Get/set candidate profile |
| POST | `/settings/profile/upload` | Upload resume (PDF/DOC/DOCX) |
| POST | `/settings/profile/reset` | Reset profile to template |
| GET/POST | `/settings/job` | Get/set job description |
| POST | `/settings/job/upload` | Upload job description file |
| POST | `/settings/job/reset` | Reset job description to template |

## Project Structure

```
AxelAiAssistant/
├── backend/
│   ├── main.py                  # FastAPI app, SSE, audio pipeline
│   ├── config.py                # Environment config
│   ├── audio_capture.py         # Mic + BlackHole audio capture
│   ├── transcription.py         # Deepgram WebSocket client
│   ├── transcription_whisper.py # Local Whisper (pywhispercpp)
│   ├── question_detector.py     # Pause-based auto-trigger + mic separation
│   ├── llm_client.py            # OpenAI + Claude streaming wrapper
│   ├── screenshot.py            # Screen capture (screencapture CLI + Pillow)
│   ├── context_manager.py       # Conversation history
│   ├── profile.md               # Candidate profile (edit before interview)
│   └── job_description.md       # Job description (edit before interview)
├── overlay/
│   ├── src/
│   │   ├── App.tsx              # Root component
│   │   ├── components/
│   │   │   ├── TopBar.tsx       # Status bar (recording, connection)
│   │   │   ├── AnswerView.tsx   # Scrollable chat-style Q&A view
│   │   │   ├── Transcript.tsx   # Compact live transcription (2 lines)
│   │   │   ├── InputBar.tsx     # Manual question input (hidden by default)
│   │   │   └── SettingsPanel.tsx # LLM/transcription/profile settings
│   │   ├── hooks/
│   │   │   ├── useSSE.ts        # SSE connection to backend
│   │   │   └── useHotkeys.ts    # Hotkey handler via IPC
│   │   └── styles/globals.css   # Tailwind + custom overlay styles
│   └── src/main/index.ts        # Electron main process (stealth, hotkeys)
├── scripts/
│   ├── dev.sh                   # Start backend + overlay (dev mode)
│   ├── setup.sh                 # Install all dependencies
│   └── build.sh                 # Build .app + .dmg
├── docs/
│   ├── ARCHITECTURE.md          # Detailed architecture docs
│   └── BUGFIX_NOTES.md          # Debug session notes
└── CLAUDE.md                    # AI assistant instructions
```

## Troubleshooting

**No sound from BlackHole**: Make sure Multi-Output Device is set as default output in System Settings → Sound.

**"BlackHole not found" error**: Install with `brew install blackhole-2ch` and restart. App works without it in mic-only mode.

**Overlay visible in screen share**: Verify the app uses `setContentProtection(true)`. On macOS 15+ (Sequoia) some apps may use ScreenCaptureKit which can bypass protection — tested OK with Zoom, Google Meet, and Yandex Telemost.

**Screenshot permission denied**: Add the app (or Terminal) to System Settings → Privacy & Security → Screen Recording. Restart the app after granting permission.

**Whisper hallucinations** ("Продолжение следует...", "Субтитры сделал..."): These are auto-filtered. If new patterns appear, add regex to `transcription_whisper.py`.

**Missing API keys**: Create `.env` from `.env.example`. Only `OPENAI_API_KEY` is required — Whisper runs locally without any API key.

## License

MIT
