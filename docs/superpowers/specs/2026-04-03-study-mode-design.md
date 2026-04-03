# Study Mode for Axel AI Assistant

## Summary

Add a "Study" mode to Axel AI Assistant for defending lab assignments via video call (Zoom). The app listens to the student and professor, auto-detects questions, and generates answers using pre-loaded lab context.

## Modes

Two modes selectable in Settings UI at the top: **Interview** (existing) | **Study** (new).

- **Interview**: current behavior — Profile + Job Description in system prompt.
- **Study**: new behavior — lab materials as context, study-oriented system prompt.

Switching mode rebuilds the system prompt and clears answer history.

## Study Mode: Lab Loading

### Folder Selection
- Settings UI shows a "Subject folder" field with a "Choose folder" button (Electron `dialog.showOpenDialog`).
- After selection, backend scans subfolders for those containing `EXPLANATION.md`.
- Each matching subfolder is a "lab" — displayed in a list with checkboxes (all checked by default).

### Context Pre-loading
- Backend reads `EXPLANATION.md` + `README.md` from each selected lab folder.
- Stores in memory as a dict: `{lab_name: {readme: str, explanation: str}}`.
- Active lab is highlighted in the list. Its context is injected into the system prompt.

### Switching Active Lab
- Click on lab in Settings list, or hotkeys `Cmd+Shift+1..9` (by order in list).
- POST `/settings/study/active-lab` triggers system prompt rebuild.
- Answer history resets on lab switch.
- SSE event `lab_switched` notifies frontend.

## System Prompt (Study Mode)

```
Ты помогаешь студенту сдавать лабораторную работу дистанционно.
Преподаватель задаёт вопросы по теории и реализации кода.

Правила:
- Отвечай кратко и по существу, на русском языке
- Если вопрос про конкретную функцию или фрагмент кода — объясни что делает и почему так реализовано
- Если вопрос по теории — дай чёткое определение и связь с кодом лабораторной
- Не говори что ты AI-ассистент, отвечай от лица студента
- Ответ должен звучать как устный ответ студента, а не как текст из учебника

ЗАДАНИЕ ЛАБОРАТОРНОЙ:
{readme_content}

РАЗБОР ЛАБОРАТОРНОЙ (теория + код):
{explanation_content}
```

## Screenshot Buffer

In Study mode, `Cmd+Shift+S` behavior changes:

1. Takes screenshot, stores in buffer (not sent immediately).
2. UI shows brief "Screenshot ready" indicator.
3. When next question is detected (pause trigger / F5 / Cmd+Shift+A), screenshot is attached to the LLM request alongside the question text.
4. Buffer clears after sending.

If no screenshot is buffered, question is processed as text-only (current behavior).

## Audio Test

New section in Settings UI (both modes): "Audio Test".

- Button "Test Audio" starts a 10-second capture of both channels (mic + BlackHole).
- No transcription — only RMS level measurement.
- SSE event `audio_level` sent every 100ms with `{mic: float, system: float}`.
- UI shows two horizontal level bars:
  - **Mic** (green) — voice input
  - **System** (blue) — system audio (BlackHole)
- Text hints based on activity:
  - Mic silent: "Speak into the microphone to test"
  - Mic active: "Microphone is working"
  - System silent: "Play some audio on your computer to test"
  - System active: "System audio is being captured"
  - BlackHole not found: "BlackHole not detected — system audio unavailable. Microphone only."
- Auto-stops after 10 seconds. Can be stopped early.

## API Changes

### New Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/settings/mode` | Get/set mode (interview/study) |
| POST | `/settings/study/folder` | Set subject folder path, trigger scan |
| GET | `/settings/study/labs` | List detected labs with load status |
| POST | `/settings/study/active-lab` | Switch active lab by index or name |
| POST | `/audio-test/start` | Start audio level test |
| POST | `/audio-test/stop` | Stop audio level test |

### New SSE Events

| Event | Data | When |
|-------|------|------|
| `audio_level` | `{mic: float, system: float}` | During audio test, every 100ms |
| `lab_switched` | `{index: int, name: str}` | Active lab changed |
| `screenshot_buffered` | `{}` | Screenshot saved to buffer |

## Backend Changes

- `llm_client.py`: new `set_mode(mode, context)` method. Two prompt templates (interview/study). Study template accepts readme + explanation content.
- `main.py`: store pre-loaded lab contexts in dict. Handle new endpoints. Audio test coroutine (10s capture, RMS calculation, SSE emit).
- `screenshot.py`: add `pending_screenshot` buffer. Attach to next question, clear after use.
- `question_detector.py`: on trigger, check for pending screenshot and include in callback.
- `config.py`: add `APP_MODE` default, study mode defaults.

## Frontend Changes

- `SettingsPanel.tsx`: mode toggle at top. Study mode section (folder picker, lab list, active lab highlight). Audio test section with level bars.
- `App.tsx`: handle `lab_switched` and `screenshot_buffered` SSE events. Show brief screenshot indicator.
- `src/main/index.ts`: register `Cmd+Shift+1..9` hotkeys for lab switching. Wire to POST `/settings/study/active-lab`.

## Hotkeys

New:
| Hotkey | Action |
|--------|--------|
| `Cmd+Shift+1..9` | Switch to lab N |

Existing (unchanged):
| Hotkey | Action |
|--------|--------|
| `Cmd+Shift+S` | Screenshot (now buffers in Study mode) |
| `Cmd+Shift+M` | Start/stop recording |
| `Cmd+Shift+A` | Force answer |
| `F5` | Mic trigger |
| All others | No changes |

## Defaults

- Default mode: Study (for today's use case)
- Default transcription: Whisper (local)
- Default LLM: keep current setting
