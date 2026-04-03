# Study Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Study mode for defending lab assignments over video call — pre-load lab contexts, switch between them via hotkeys, buffer screenshots for next question, and test audio before sessions.

**Architecture:** New mode toggle (interview/study) controls which system prompt template LLM uses. Backend stores pre-loaded lab contexts in a dict. Frontend adds mode switcher and lab list to SettingsPanel. Screenshot buffer attaches to next question trigger. Audio test uses existing AudioCapture with RMS-level SSE events.

**Tech Stack:** Python (FastAPI), TypeScript (Electron + React), existing audio/LLM/SSE infrastructure.

---

### Task 1: Backend — Mode and Lab Management Endpoints

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Add mode config to `backend/config.py`**

Add at the end of `config.py`:

```python
# App mode: "interview" or "study"
APP_MODE = os.getenv("APP_MODE", "study")
```

- [ ] **Step 2: Add mode and lab state to `backend/main.py`**

Add after the module instances block (after line 51):

```python
# App mode and study context
_current_mode = "study"  # "interview" or "study"
_study_labs: list[dict] = []  # [{name, readme, explanation, folder}]
_active_lab_index: int = -1
_study_folder: str = ""
```

- [ ] **Step 3: Add `/settings/mode` endpoints to `backend/main.py`**

Add after the transcription settings section (after line 475):

```python
# --- Mode settings ---

@app.get("/settings/mode")
async def get_mode():
    """Get current app mode."""
    return {"mode": _current_mode}


@app.post("/settings/mode")
async def set_mode(request: Request):
    """Switch between interview and study mode."""
    global _current_mode
    body = await request.json()
    mode = body.get("mode", _current_mode)
    if mode not in ("interview", "study"):
        return {"status": "error", "message": f"Unknown mode: {mode}"}
    _current_mode = mode
    _rebuild_system_prompt()
    context.exchanges.clear()
    return {"status": "ok", "mode": mode}
```

- [ ] **Step 4: Add `/settings/study/folder` endpoint**

Add after the mode endpoints:

```python
@app.post("/settings/study/folder")
async def set_study_folder(request: Request):
    """Set the subject folder and scan for labs."""
    global _study_folder, _study_labs, _active_lab_index
    body = await request.json()
    folder = body.get("folder", "").strip()

    if not folder or not os.path.isdir(folder):
        return {"status": "error", "message": "Invalid folder path"}

    _study_folder = folder
    _study_labs = []
    _active_lab_index = -1

    # Scan subfolders for labs (must contain EXPLANATION.md)
    for entry in sorted(os.listdir(folder)):
        sub = os.path.join(folder, entry)
        if not os.path.isdir(sub):
            continue
        expl_path = os.path.join(sub, "EXPLANATION.md")
        if not os.path.isfile(expl_path):
            continue
        readme_path = os.path.join(sub, "README.md")
        readme = ""
        if os.path.isfile(readme_path):
            with open(readme_path, "r", encoding="utf-8") as f:
                readme = f.read()
        with open(expl_path, "r", encoding="utf-8") as f:
            explanation = f.read()
        _study_labs.append({
            "name": entry,
            "folder": sub,
            "readme": readme,
            "explanation": explanation,
        })

    # Auto-select first lab
    if _study_labs:
        _active_lab_index = 0
        _rebuild_system_prompt()

    logger.info(f"Study folder: {folder}, found {len(_study_labs)} labs")
    return {
        "status": "ok",
        "folder": folder,
        "labs": [{"name": l["name"], "index": i} for i, l in enumerate(_study_labs)],
        "active_index": _active_lab_index,
    }
```

- [ ] **Step 5: Add `/settings/study/labs` and `/settings/study/active-lab` endpoints**

```python
@app.get("/settings/study/labs")
async def get_study_labs():
    """List detected labs and active selection."""
    return {
        "folder": _study_folder,
        "labs": [{"name": l["name"], "index": i} for i, l in enumerate(_study_labs)],
        "active_index": _active_lab_index,
    }


@app.post("/settings/study/active-lab")
async def set_active_lab(request: Request):
    """Switch active lab by index."""
    global _active_lab_index
    body = await request.json()
    index = body.get("index", -1)

    if not _study_labs:
        return {"status": "error", "message": "No labs loaded"}
    if index < 0 or index >= len(_study_labs):
        return {"status": "error", "message": f"Invalid lab index: {index}"}

    _active_lab_index = index
    _rebuild_system_prompt()
    context.exchanges.clear()
    lab_name = _study_labs[index]["name"]
    await emit_event("lab_switched", {"index": index, "name": lab_name})
    logger.info(f"Switched to lab [{index}]: {lab_name}")
    return {"status": "ok", "index": index, "name": lab_name}
```

- [ ] **Step 6: Add `_rebuild_system_prompt()` helper**

Add before the mode endpoints:

```python
def _rebuild_system_prompt():
    """Rebuild LLM system prompt based on current mode and active lab."""
    if _current_mode == "study" and _study_labs and 0 <= _active_lab_index < len(_study_labs):
        lab = _study_labs[_active_lab_index]
        llm.set_study_context(lab["readme"], lab["explanation"])
    else:
        llm.set_interview_mode()
```

- [ ] **Step 7: Verify backend starts without errors**

Run: `cd /Users/user/Desktop/Work/PetProjects/AxelAiAssistant/backend && python3 -c "import main; print('OK')"`

Expected: OK (no import errors)

- [ ] **Step 8: Commit**

```bash
git add backend/config.py backend/main.py
git commit -m "feat: add mode switching and lab management endpoints"
```

---

### Task 2: Backend — LLM Client Study Mode Prompts

**Files:**
- Modify: `backend/llm_client.py`

- [ ] **Step 1: Add mode tracking and study prompt to LLMClient**

Replace the `__init__`, `set_provider`, `reload_system_prompt`, and `_build_system_prompt` methods. Add new methods. After the existing `set_provider` method (line 44), add:

```python
    def set_study_context(self, readme: str, explanation: str):
        """Switch to study mode with lab context."""
        self._mode = "study"
        self._study_readme = readme
        self._study_explanation = explanation
        self.system_prompt = self._build_study_prompt(readme, explanation)
        logger.info("System prompt set to study mode")

    def set_interview_mode(self):
        """Switch back to interview mode."""
        self._mode = "interview"
        self.system_prompt = self._build_system_prompt()
        logger.info("System prompt set to interview mode")

    @staticmethod
    def _build_study_prompt(readme: str, explanation: str) -> str:
        return f"""Ты помогаешь студенту сдавать лабораторную работу дистанционно.
Преподаватель задаёт вопросы по теории и реализации кода.

ПРАВИЛА:
1. Отвечай КРАТКО и ПО СУЩЕСТВУ, на русском языке
2. Если вопрос про конкретную функцию или фрагмент кода — объясни что делает и почему так реализовано
3. Если вопрос по теории — дай чёткое определение и связь с кодом лабораторной
4. Не говори что ты AI-ассистент, отвечай от лица студента
5. Ответ должен звучать как устный ответ студента, а не как текст из учебника
6. Максимум 150-200 слов, если не задача по коду
7. Текст вопроса получен через автоматическую транскрипцию речи — он может содержать ошибки распознавания. Попробуй понять истинный смысл вопроса из контекста лабораторной работы

ЗАДАНИЕ ЛАБОРАТОРНОЙ:
{readme}

РАЗБОР ЛАБОРАТОРНОЙ (теория + код):
{explanation}"""
```

- [ ] **Step 2: Initialize mode fields in `__init__`**

Add after `self.system_prompt = self._build_system_prompt()` (line 32):

```python
        self._mode = "interview"
        self._study_readme = ""
        self._study_explanation = ""
```

- [ ] **Step 3: Update `generate_answer` message framing for study mode**

In `generate_answer`, the current question messages say "Вопрос интервьюера:". For study mode, change this. Replace the history loop (lines 157-166) and current question section (lines 168-184):

```python
        # Label depends on mode
        q_prefix = "Вопрос преподавателя:" if self._mode == "study" else "Вопрос интервьюера:"

        # Add conversation history (with what candidate actually said)
        for exchange in context_history:
            messages.append({"role": "user",
                             "content": f"{q_prefix} {exchange['question']}"})
            if exchange.get("answer"):
                answer_content = exchange["answer"]
                if exchange.get("candidate_said"):
                    answer_content += f"\n\n[Кандидат реально ответил: {exchange['candidate_said']}]"
                messages.append({"role": "assistant",
                                 "content": answer_content})

        # Current question
        if screenshot_b64:
            screenshot_hint = "На скриншоте — код или задача, которую обсуждают." if self._mode == "study" else "На скриншоте — задача или код."
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text",
                     "text": f"{q_prefix} {question}\n\n{screenshot_hint}"},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{screenshot_b64}",
                        "detail": "high",
                    }},
                ],
            })
            use_model = self._get_vision_model()
        else:
            messages.append({"role": "user",
                             "content": f"{q_prefix} {question}"})
```

- [ ] **Step 4: Commit**

```bash
git add backend/llm_client.py
git commit -m "feat: add study mode prompt and context switching to LLM client"
```

---

### Task 3: Backend — Screenshot Buffer

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/screenshot.py`

- [ ] **Step 1: Add screenshot buffer state to `backend/main.py`**

Add after the study state variables:

```python
# Screenshot buffer for study mode (attach to next question)
_pending_screenshot: str | None = None
```

- [ ] **Step 2: Add `/screenshot/buffer` endpoint for study mode**

Add a new endpoint that buffers a screenshot instead of immediately analyzing it:

```python
@app.post("/screenshot/buffer")
async def buffer_screenshot():
    """Capture screenshot and buffer it for the next question (study mode)."""
    global _pending_screenshot
    try:
        img_b64 = screenshot_capture.capture_full_screen()
        _pending_screenshot = img_b64
        await emit_event("screenshot_buffered", {})
        logger.info(f"Screenshot buffered ({len(img_b64)} bytes b64)")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Screenshot buffer failed: {e}")
        await emit_event("status", {"type": "error", "message": f"Screenshot failed: {e}"})
        return {"status": "error", "message": str(e)}
```

- [ ] **Step 3: Modify `on_question_detected` to attach pending screenshot**

Replace the `on_question_detected` function:

```python
async def on_question_detected(question_text: str):
    """Callback when a question is detected — start answer generation."""
    global _current_generation, _pending_screenshot

    # Cancel previous generation if still running
    if _current_generation and not _current_generation.done():
        _current_generation.cancel()

    answer_id = str(uuid.uuid4())[:8]
    context.add_question(question_text)
    await emit_event("question_detected", {"text": question_text})
    await emit_event("ai_answer_start", {"question": question_text, "id": answer_id})

    # Attach buffered screenshot if available
    screenshot_b64 = None
    if _pending_screenshot:
        screenshot_b64 = _pending_screenshot
        _pending_screenshot = None
        logger.info("Attaching buffered screenshot to question")

    _current_generation = asyncio.create_task(
        _generate_answer(question_text, answer_id, screenshot_b64=screenshot_b64)
    )
```

- [ ] **Step 4: Modify Cmd+Shift+S hotkey to buffer in study mode**

This change is in Electron (Task 5), but the backend also needs to know the mode. The frontend will call `/screenshot/buffer` when in study mode, or `/screenshot` when in interview mode. No additional backend change needed.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: add screenshot buffer for study mode question attachment"
```

---

### Task 4: Backend — Audio Test Endpoints

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add audio test state and endpoints**

Add after the screenshot buffer section:

```python
# --- Audio Test ---

_audio_test_task: asyncio.Task | None = None


async def _run_audio_test():
    """Run audio level test for 10 seconds, emitting RMS levels via SSE."""
    import janus
    test_mic_queue = janus.Queue()
    test_system_queue = janus.Queue()

    mic_stream = None
    system_stream = None

    try:
        # Find devices
        default_input = sd.default.device[0]
        if default_input is not None and default_input >= 0:
            mic_idx = int(default_input)
        else:
            mic_idx = audio._find_any_mic()

        mic_rate = audio._get_device_rate(mic_idx)
        mic_block = int(mic_rate * 0.1)

        def mic_cb(indata, frames, time_info, status):
            test_mic_queue.sync_q.put_nowait(indata[:, 0].copy())

        mic_stream = sd.InputStream(
            device=mic_idx, channels=1, samplerate=mic_rate,
            dtype='int16', blocksize=mic_block, callback=mic_cb,
        )
        mic_stream.start()

        # Try BlackHole
        blackhole_idx = None
        try:
            blackhole_idx = audio.find_device("BlackHole")
        except ValueError:
            pass

        if blackhole_idx is not None:
            sys_rate = audio._get_device_rate(blackhole_idx)
            sys_block = int(sys_rate * 0.1)

            def sys_cb(indata, frames, time_info, status):
                test_system_queue.sync_q.put_nowait(indata[:, 0].copy())

            system_stream = sd.InputStream(
                device=blackhole_idx, channels=1, samplerate=sys_rate,
                dtype='int16', blocksize=sys_block, callback=sys_cb,
            )
            system_stream.start()

        has_system = blackhole_idx is not None

        # Emit levels for 10 seconds
        for _ in range(100):  # 100 * 0.1s = 10s
            await asyncio.sleep(0.1)

            mic_rms = 0.0
            try:
                while not test_mic_queue.async_q.empty():
                    chunk = test_mic_queue.async_q.get_nowait()
                    rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                    mic_rms = max(mic_rms, rms)
            except Exception:
                pass

            sys_rms = 0.0
            if has_system:
                try:
                    while not test_system_queue.async_q.empty():
                        chunk = test_system_queue.async_q.get_nowait()
                        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                        sys_rms = max(sys_rms, rms)
                except Exception:
                    pass

            # Normalize to 0-1 range (int16 max RMS ~23000 for loud signal)
            await emit_event("audio_level", {
                "mic": min(1.0, mic_rms / 8000),
                "system": min(1.0, sys_rms / 8000) if has_system else -1,
            })

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Audio test error: {e}")
        await emit_event("status", {"type": "error", "message": f"Audio test error: {e}"})
    finally:
        if mic_stream:
            mic_stream.stop()
            mic_stream.close()
        if system_stream:
            system_stream.stop()
            system_stream.close()
        test_mic_queue.close()
        test_system_queue.close()
        await emit_event("audio_test_done", {})


@app.post("/audio-test/start")
async def start_audio_test():
    """Start a 10-second audio level test."""
    global _audio_test_task
    if audio.is_recording:
        return {"status": "error", "message": "Stop recording before testing audio"}
    if _audio_test_task and not _audio_test_task.done():
        return {"status": "error", "message": "Audio test already running"}
    _audio_test_task = asyncio.create_task(_run_audio_test())
    return {"status": "ok"}


@app.post("/audio-test/stop")
async def stop_audio_test():
    """Stop audio level test early."""
    global _audio_test_task
    if _audio_test_task and not _audio_test_task.done():
        _audio_test_task.cancel()
    return {"status": "ok"}
```

- [ ] **Step 2: Add missing imports at top of `main.py`**

Add `import sounddevice as sd` and `import numpy as np` to the imports if not already present:

```python
import sounddevice as sd
import numpy as np
```

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: add audio test endpoints with RMS level streaming"
```

---

### Task 5: Electron — Lab Switching Hotkeys and Screenshot Mode

**Files:**
- Modify: `overlay/src/main/index.ts`

- [ ] **Step 1: Add lab switching hotkeys in `registerHotkeys()`**

Add after the opacity hotkeys (after line 153):

```typescript
  // Lab switching hotkeys (Cmd+Shift+1..9)
  for (let i = 1; i <= 9; i++) {
    globalShortcut.register(`CommandOrControl+Shift+${i}`, () => {
      fetch('http://127.0.0.1:8765/settings/study/active-lab', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index: i - 1 }),
      }).catch(() => {})
    })
  }
```

- [ ] **Step 2: Modify Cmd+Shift+S to check mode**

Replace the screenshot hotkey registration (lines 129-131):

```typescript
  // Screenshot — buffer in study mode, analyze in interview mode
  globalShortcut.register('CommandOrControl+Shift+S', async () => {
    try {
      const modeRes = await fetch('http://127.0.0.1:8765/settings/mode')
      const { mode } = await modeRes.json()
      const endpoint = mode === 'study' ? '/screenshot/buffer' : '/screenshot'
      await fetch(`http://127.0.0.1:8765${endpoint}`, { method: 'POST' })
    } catch {
      // Fallback to regular screenshot
      fetch('http://127.0.0.1:8765/screenshot', { method: 'POST' }).catch(() => {})
    }
  })
```

- [ ] **Step 3: Commit**

```bash
git add overlay/src/main/index.ts
git commit -m "feat: add lab switching hotkeys and study mode screenshot buffer"
```

---

### Task 6: Frontend — useSSE Hook Updates

**Files:**
- Modify: `overlay/src/hooks/useSSE.ts`

- [ ] **Step 1: Add new SSE event handlers**

Add `screenshotBuffered` and `activeLab` to state interface:

```typescript
interface SSEState {
  transcripts: TranscriptLine[]
  answers: AnswerEntry[]
  pendingQuestion: string | null
  isRecording: boolean
  isConnected: boolean
  error: string | null
  statusMessage: string | null
  screenshotBuffered: boolean
  activeLab: { index: number; name: string } | null
}
```

Update initial state:

```typescript
  const [state, setState] = useState<SSEState>({
    transcripts: [],
    answers: [],
    pendingQuestion: null,
    isRecording: false,
    isConnected: false,
    error: null,
    statusMessage: null,
    screenshotBuffered: false,
    activeLab: null,
  })
```

- [ ] **Step 2: Add event listeners in `connect()`**

Add after the existing `status` event listener (after line 132):

```typescript
    es.addEventListener('screenshot_buffered', () => {
      setState((s) => ({ ...s, screenshotBuffered: true }))
      // Auto-clear after 5 seconds
      setTimeout(() => {
        setState((s) => ({ ...s, screenshotBuffered: false }))
      }, 5000)
    })

    es.addEventListener('lab_switched', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => ({
        ...s,
        activeLab: { index: data.index, name: data.name },
        answers: [],  // Clear answers on lab switch
      }))
    })

    es.addEventListener('audio_level', (e) => {
      const data = JSON.parse(e.data)
      // Dispatch custom event for AudioTest component
      window.dispatchEvent(new CustomEvent('audio-level', { detail: data }))
    })

    es.addEventListener('audio_test_done', () => {
      window.dispatchEvent(new CustomEvent('audio-test-done'))
    })
```

- [ ] **Step 3: Clear screenshot flag when question triggers**

In the `ai_answer_start` handler, add `screenshotBuffered: false`:

```typescript
    es.addEventListener('ai_answer_start', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => {
        const newEntry: AnswerEntry = {
          question: data.question || s.pendingQuestion || '',
          answer: '',
          isComplete: false,
        }
        return {
          ...s,
          answers: [...s.answers, newEntry],
          pendingQuestion: null,
          screenshotBuffered: false,
        }
      })
    })
```

- [ ] **Step 4: Commit**

```bash
git add overlay/src/hooks/useSSE.ts
git commit -m "feat: add screenshot_buffered, lab_switched, audio_level SSE events"
```

---

### Task 7: Frontend — SettingsPanel Mode Switcher and Study Section

**Files:**
- Modify: `overlay/src/components/SettingsPanel.tsx`

- [ ] **Step 1: Add mode and study state to SettingsPanel**

Add to the Props interface:

```typescript
interface Props {
  isOpen: boolean
  onClose: () => void
  opacity: number
  onOpacityChange: (value: number) => void
  clickThrough: boolean
  onClickThroughChange: (value: boolean) => void
  autoAnswer: boolean
  onAutoAnswerChange: (value: boolean) => void
  activeLab: { index: number; name: string } | null
}
```

Add state variables inside the component (after existing state):

```typescript
  const [mode, setMode] = useState<'interview' | 'study'>('study')
  const [studyFolder, setStudyFolder] = useState('')
  const [labs, setLabs] = useState<{ name: string; index: number }[]>([])
  const [activeLabIndex, setActiveLabIndex] = useState(-1)
  const [audioTesting, setAudioTesting] = useState(false)
  const [micLevel, setMicLevel] = useState(0)
  const [systemLevel, setSystemLevel] = useState(0)
  const [systemAvailable, setSystemAvailable] = useState(true)
```

- [ ] **Step 2: Load mode and study data on open**

Add to the existing `useEffect` that loads settings when panel opens:

```typescript
  useEffect(() => {
    if (!isOpen) return
    // Existing loads...
    fetch(`${BACKEND_URL}/settings/mode`)
      .then((r) => r.json())
      .then((data) => setMode(data.mode))
      .catch(() => {})
    fetch(`${BACKEND_URL}/settings/study/labs`)
      .then((r) => r.json())
      .then((data) => {
        setStudyFolder(data.folder || '')
        setLabs(data.labs || [])
        setActiveLabIndex(data.active_index ?? -1)
      })
      .catch(() => {})
  }, [isOpen])
```

- [ ] **Step 3: Add mode switch handler**

```typescript
  const handleModeChange = async (newMode: 'interview' | 'study') => {
    setMode(newMode)
    try {
      await fetch(`${BACKEND_URL}/settings/mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: newMode }),
      })
    } catch {}
  }
```

- [ ] **Step 4: Add folder selection handler**

```typescript
  const handleSelectFolder = async () => {
    // Use prompt as Electron dialog requires IPC — for now, simple text input
    const folder = prompt('Путь к папке предмета:', studyFolder || '/Users/user/Documents/PSU/3.2/Распознование образов')
    if (!folder) return
    try {
      const res = await fetch(`${BACKEND_URL}/settings/study/folder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder }),
      })
      const data = await res.json()
      if (data.status === 'ok') {
        setStudyFolder(data.folder)
        setLabs(data.labs || [])
        setActiveLabIndex(data.active_index ?? -1)
      }
    } catch {}
  }
```

- [ ] **Step 5: Add lab switch handler**

```typescript
  const handleLabSwitch = async (index: number) => {
    try {
      const res = await fetch(`${BACKEND_URL}/settings/study/active-lab`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index }),
      })
      const data = await res.json()
      if (data.status === 'ok') {
        setActiveLabIndex(index)
      }
    } catch {}
  }
```

- [ ] **Step 6: Add audio test handlers**

```typescript
  // Audio test level listener
  useEffect(() => {
    if (!audioTesting) return
    const handleLevel = (e: Event) => {
      const { mic, system } = (e as CustomEvent).detail
      setMicLevel(mic)
      if (system === -1) {
        setSystemAvailable(false)
        setSystemLevel(0)
      } else {
        setSystemAvailable(true)
        setSystemLevel(system)
      }
    }
    const handleDone = () => setAudioTesting(false)
    window.addEventListener('audio-level', handleLevel)
    window.addEventListener('audio-test-done', handleDone)
    return () => {
      window.removeEventListener('audio-level', handleLevel)
      window.removeEventListener('audio-test-done', handleDone)
    }
  }, [audioTesting])

  const handleStartAudioTest = async () => {
    setAudioTesting(true)
    setMicLevel(0)
    setSystemLevel(0)
    setSystemAvailable(true)
    try {
      await fetch(`${BACKEND_URL}/audio-test/start`, { method: 'POST' })
    } catch {
      setAudioTesting(false)
    }
  }

  const handleStopAudioTest = async () => {
    try {
      await fetch(`${BACKEND_URL}/audio-test/stop`, { method: 'POST' })
    } catch {}
    setAudioTesting(false)
  }
```

- [ ] **Step 7: Add mode toggle UI at the top of settings body**

Insert right after the header `div`, before `{/* Settings content */}`:

```tsx
        {/* Mode Toggle */}
        <div className="px-4 pt-4 pb-2">
          <div className="text-[13px] font-medium text-[var(--text-primary)] mb-2.5">Режим</div>
          <div className="flex gap-2">
            <button
              className={`setting-chip ${mode === 'interview' ? 'active' : ''}`}
              onClick={() => handleModeChange('interview')}
            >
              Собеседование
            </button>
            <button
              className={`setting-chip ${mode === 'study' ? 'active' : ''}`}
              onClick={() => handleModeChange('study')}
            >
              Учёба
            </button>
          </div>
        </div>
```

- [ ] **Step 8: Add study mode section (folder + labs)**

Insert after the mode toggle, conditionally rendered when `mode === 'study'`:

```tsx
        {mode === 'study' && (
          <div className="px-4 pb-3">
            <div style={{ height: 1, background: 'var(--border)', margin: '4px -16px 12px', width: 'calc(100% + 32px)' }} />
            <div className="text-[13px] font-medium text-[var(--text-primary)] mb-2">Предмет</div>
            <div className="flex items-center gap-2 mb-3">
              <div className="flex-1 text-[11px] text-[var(--text-secondary)] truncate">
                {studyFolder || 'Папка не выбрана'}
              </div>
              <button className="setting-chip" onClick={handleSelectFolder}>
                Выбрать папку
              </button>
            </div>

            {labs.length > 0 && (
              <>
                <div className="text-[13px] font-medium text-[var(--text-primary)] mb-2">
                  Лабораторные ({labs.length})
                </div>
                <div className="space-y-1">
                  {labs.map((lab) => (
                    <button
                      key={lab.index}
                      className={`w-full text-left px-3 py-2 rounded-lg text-[12px] transition-colors cursor-pointer ${
                        activeLabIndex === lab.index
                          ? 'bg-[rgba(110,123,242,0.15)] text-[var(--accent)]'
                          : 'text-[var(--text-secondary)] hover:bg-[rgba(255,255,255,0.04)]'
                      }`}
                      onClick={() => handleLabSwitch(lab.index)}
                    >
                      <span className="font-medium text-[var(--text-tertiary)] mr-2">
                        {lab.index + 1}.
                      </span>
                      {lab.name}
                    </button>
                  ))}
                </div>
                <div className="text-[10px] text-[var(--text-tertiary)] mt-2">
                  Переключение: Cmd+Shift+1..{Math.min(labs.length, 9)}
                </div>
              </>
            )}
          </div>
        )}
```

- [ ] **Step 9: Add audio test section**

Insert before the hotkeys section:

```tsx
          {/* Audio Test */}
          <div style={{ borderTop: '1px solid var(--border)' }}>
            <div className="px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[13px] font-medium text-[var(--text-primary)]">Тест аудио</span>
                <button
                  className="setting-chip"
                  onClick={audioTesting ? handleStopAudioTest : handleStartAudioTest}
                >
                  {audioTesting ? 'Остановить' : 'Проверить'}
                </button>
              </div>
              {audioTesting && (
                <div className="space-y-2">
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] text-[var(--text-secondary)]">Микрофон</span>
                      <span className="text-[10px] text-[var(--text-tertiary)]">
                        {micLevel > 0.05 ? 'Работает' : 'Говорите в микрофон'}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-[rgba(255,255,255,0.06)] overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-100"
                        style={{
                          width: `${Math.min(100, micLevel * 100)}%`,
                          backgroundColor: 'var(--accent-green)',
                        }}
                      />
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] text-[var(--text-secondary)]">Системный звук</span>
                      <span className="text-[10px] text-[var(--text-tertiary)]">
                        {!systemAvailable
                          ? 'BlackHole не найден'
                          : systemLevel > 0.05
                            ? 'Захватывается'
                            : 'Включите звук на компьютере'}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-[rgba(255,255,255,0.06)] overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-100"
                        style={{
                          width: `${Math.min(100, systemLevel * 100)}%`,
                          backgroundColor: systemAvailable ? 'var(--accent)' : 'var(--accent-red)',
                        }}
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
```

- [ ] **Step 10: Wrap Profile/Job sections in interview mode guard**

Wrap the existing EditableSection components so they only show in interview mode:

```tsx
        {mode === 'interview' && (
          <>
            {/* Profile section */}
            <EditableSection
              title="Профиль кандидата"
              subtitle="Резюме для системного промпта AI"
              endpoint="profile"
              uploadEndpoint="profile/upload"
              resetEndpoint="profile/reset"
              placeholder={"# Профиль кандидата\n..."}
              isOpen={isOpen}
            />
            {/* Job description section */}
            <EditableSection
              title="Вакансия"
              subtitle="Описание позиции для контекста AI"
              endpoint="job"
              uploadEndpoint="job/upload"
              resetEndpoint="job/reset"
              processEndpoint="job/process"
              placeholder={"# Описание вакансии\n..."}
              isOpen={isOpen}
            />
          </>
        )}
```

- [ ] **Step 11: Update Props destructuring to include `activeLab`**

Update the component function signature:

```typescript
export function SettingsPanel({
  isOpen,
  onClose,
  opacity,
  onOpacityChange,
  clickThrough,
  onClickThroughChange,
  autoAnswer,
  onAutoAnswerChange,
  activeLab,
}: Props) {
```

Sync external lab switch (from hotkey) with local state:

```typescript
  useEffect(() => {
    if (activeLab) {
      setActiveLabIndex(activeLab.index)
    }
  }, [activeLab])
```

- [ ] **Step 12: Commit**

```bash
git add overlay/src/components/SettingsPanel.tsx
git commit -m "feat: add mode toggle, lab list, and audio test to SettingsPanel"
```

---

### Task 8: Frontend — App.tsx Integration

**Files:**
- Modify: `overlay/src/App.tsx`

- [ ] **Step 1: Pass new props to SettingsPanel**

Update the `useSSE` destructuring to include new fields:

```typescript
  const {
    answers,
    pendingQuestion,
    isRecording,
    isConnected,
    transcripts,
    error,
    statusMessage,
    clearError,
    screenshotBuffered,
    activeLab,
  } = useSSE()
```

- [ ] **Step 2: Add screenshot indicator to the UI**

Add after the error toast, before `inputBarVisible`:

```tsx
      {/* Screenshot buffered indicator */}
      {screenshotBuffered && (
        <div className="status-toast" style={{ borderColor: 'var(--accent)' }}>
          <span className="status-toast-text">Screenshot ready — ответ включит скриншот</span>
        </div>
      )}
```

- [ ] **Step 3: Pass `activeLab` to SettingsPanel**

Add the prop to the SettingsPanel component:

```tsx
      {settingsMounted && (
        <SettingsPanel
          isOpen={settingsOpen}
          onClose={handleCloseSettings}
          opacity={opacity}
          onOpacityChange={handleOpacityChange}
          clickThrough={clickThrough}
          onClickThroughChange={handleClickThroughChange}
          autoAnswer={autoAnswer}
          onAutoAnswerChange={setAutoAnswer}
          activeLab={activeLab}
        />
      )}
```

- [ ] **Step 4: Commit**

```bash
git add overlay/src/App.tsx
git commit -m "feat: integrate screenshot indicator and lab state into App"
```

---

### Task 9: Build Verification and Smoke Test

**Files:** None (verification only)

- [ ] **Step 1: Build the Electron app**

Run: `cd /Users/user/Desktop/Work/PetProjects/AxelAiAssistant/overlay && npx electron-vite build`

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 2: Check Python backend starts**

Run: `cd /Users/user/Desktop/Work/PetProjects/AxelAiAssistant/backend && timeout 5 python3 main.py || true`

Expected: Backend starts without import errors (will timeout after 5s, that's fine).

- [ ] **Step 3: Test lab scanning endpoint manually**

Run:
```bash
cd /Users/user/Desktop/Work/PetProjects/AxelAiAssistant/backend
python3 -c "
import asyncio, json
from main import app
from fastapi.testclient import TestClient

client = TestClient(app)
r = client.post('/settings/study/folder', json={'folder': '/Users/user/Documents/PSU/3.2/Распознование образов'})
data = r.json()
print(json.dumps(data, indent=2, ensure_ascii=False))
assert data['status'] == 'ok'
assert len(data['labs']) == 4
print('Lab scan: OK')
"
```

Expected: 4 labs found, status OK.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: study mode complete — lab loading, mode switching, audio test, screenshot buffer"
```
