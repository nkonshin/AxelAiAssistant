# Архитектура проекта — AI Interview Assistant

## Обзор

AI Interview Assistant — невидимый ассистент для технических собеседований на macOS. Приложение в реальном времени слушает аудио собеседования, транскрибирует речь, автоматически детектирует вопросы интервьюера и генерирует подсказки-ответы в невидимом overlay поверх экрана.

Ключевая особенность — overlay **невидим при демонстрации экрана** в Zoom, Google Meet и Microsoft Teams.

---

## Технологический стек

### Python Backend

| Технология | Версия | Назначение |
|---|---|---|
| **Python** | 3.11+ | Основной язык бэкенда |
| **FastAPI** | 0.115+ | HTTP API + SSE стриминг |
| **uvicorn** | 0.34+ | ASGI сервер |
| **sse-starlette** | 2.2+ | Server-Sent Events для стриминга ответов |
| **sounddevice** | 0.5+ | Захват аудио с микрофона и BlackHole |
| **numpy** | 2.2+ | Обработка аудио-буферов, ресемплинг |
| **janus** | 2.0+ | Thread-safe очереди (связь sounddevice callbacks с asyncio) |
| **websockets** | 14.2+ | WebSocket клиент для Deepgram API |
| **openai** | 1.59+ | GPT-4o / GPT-4o-mini стриминг |
| **Pillow** | 11.1+ | Захват скриншотов экрана |
| **python-dotenv** | 1.0+ | Загрузка переменных окружения |

### Electron Overlay

| Технология | Версия | Назначение |
|---|---|---|
| **Electron** | 28+ | Десктопное приложение с нативным API |
| **React** | 18.3 | UI компоненты |
| **TypeScript** | 5.6 | Типизация |
| **Tailwind CSS** | 3.4 | Стилизация overlay |
| **electron-vite** | 2.3 | Сборка Electron + Vite |
| **react-markdown** | 9.0 | Рендеринг Markdown в ответах |
| **react-syntax-highlighter** | 15.5 | Подсветка синтаксиса в блоках кода |
| **remark-gfm** | 4.0 | GitHub Flavored Markdown |

### Внешние сервисы

| Сервис | Назначение |
|---|---|
| **Deepgram Nova-3** | Real-time транскрипция через WebSocket (русский язык) |
| **OpenAI GPT-4o** | Генерация ответов + анализ скриншотов (Vision) |
| **OpenAI GPT-4o-mini** | Быстрые ответы на простые вопросы |

### Системные зависимости (macOS)

| Компонент | Назначение |
|---|---|
| **BlackHole 2ch** | Виртуальный аудио-драйвер для захвата системного звука |
| **portaudio** | Бэкенд для библиотеки sounddevice |

---

## Архитектура системы

```
┌─────────────────────────────────────────────────────────┐
│                 Electron (Overlay UI)                     │
│                                                           │
│   React + TypeScript + Tailwind CSS                       │
│   setContentProtection(true) — невидим при screen share   │
│   Transparent, frameless, always-on-top, click-through    │
│                                                           │
│   ┌──────────┐ ┌────────────┐ ┌──────────┐ ┌──────────┐ │
│   │StatusBar │ │ Transcript │ │ Overlay  │ │ Controls │ │
│   │(drag)    │ │(collapsible)│ │(answers) │ │(buttons) │ │
│   └──────────┘ └────────────┘ └──────────┘ └──────────┘ │
└───────────┬─────────────────────────┬────────────────────┘
            │ SSE (события)           │ HTTP (команды)
            ▼                         ▼
┌─────────────────────────────────────────────────────────┐
│                Python Backend (FastAPI)                    │
│                localhost:8765                              │
│                                                           │
│   ┌──────────────┐    ┌──────────────┐    ┌────────────┐ │
│   │ AudioCapture │───▶│ Transcription│───▶│  Question  │ │
│   │              │    │  (Deepgram)  │    │  Detector  │ │
│   │ Mic ──── Q1  │    │  WebSocket   │    │ Heuristics │ │
│   │ BH  ──── Q2  │    │  Nova-3 RU   │    │ + Debounce │ │
│   └──────────────┘    └──────────────┘    └─────┬──────┘ │
│                                                  │        │
│   ┌──────────────┐    ┌──────────────┐    ┌─────▼──────┐ │
│   │  Screenshot  │    │   Context    │    │    LLM     │ │
│   │   Capture    │───▶│   Manager    │◀──▶│   Client   │ │
│   │   (Pillow)   │    │  (History)   │    │(GPT-4o SSE)│ │
│   └──────────────┘    └──────────────┘    └────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

## Поток данных (Pipeline)

### Основной pipeline: аудио → ответ

```
1. AudioCapture
   ├── Микрофон (Built-in) ──▶ mic_queue
   └── BlackHole 2ch ────────▶ system_queue

2. audio_to_deepgram() [2 корутины]
   ├── mic_queue ────▶ DeepgramTranscriber (mic)
   └── system_queue ─▶ DeepgramTranscriber (system)

3. DeepgramTranscriber._receive_loop()
   ├── speech_final ──▶ on_transcript() ──▶ QuestionDetector.add_transcript()
   └── UtteranceEnd ──▶ on_utterance_end() ──▶ QuestionDetector.on_utterance_end()

4. QuestionDetector._trigger()
   └──▶ on_question_detected()

5. _generate_answer() [asyncio.Task]
   ├── LLMClient.generate_answer() [streaming]
   │   └── Каждый chunk ──▶ emit_event("ai_answer_chunk")
   └── emit_event("ai_answer_end")

6. SSE ──▶ EventSource в React ──▶ Overlay UI
```

### Pipeline скриншота

```
1. Горячая клавиша Cmd+Shift+S
2. HTTP POST /screenshot
3. ScreenshotCapture.capture_full_screen() → base64 JPEG
4. LLMClient.generate_answer(screenshot_b64=...) → GPT-4o Vision
5. SSE streaming → Overlay UI
```

---

## Ключевые модули

### `audio_capture.py` — Захват аудио

- Два параллельных `sounddevice.InputStream`: микрофон + BlackHole
- **Thread-safe очереди через `janus.Queue`** — sounddevice callbacks выполняются в C-потоке, а не в asyncio event loop. Прямой `asyncio.Queue.put_nowait()` из callback-а — race condition. janus предоставляет `sync_q` (для callback) и `async_q` (для корутин)
- Автоматический поиск устройств по имени ("MacBook", "Built-in", "BlackHole")
- Ресемплинг через numpy если нативная частота устройства != 16kHz
- Формат: 16kHz, mono, int16 (PCM) — требование Deepgram

### `transcription.py` — Deepgram WebSocket

- Прямое подключение к `wss://api.deepgram.com/v1/listen` через websockets
- Модель Nova-3 с русским языком (`language=ru`)
- `interim_results=true` — промежуточные результаты для отзывчивости UI
- `endpointing=300` — 300мс тишины = конец фразы
- `utterance_end_ms=1000` — 1с тишины = конец высказывания (триггер для детектора)
- **Auto-reconnect** с exponential backoff (до 5 попыток) при обрыве соединения

### `question_detector.py` — Детекция вопросов

Три стратегии детекции:

1. **По паузе** (основная): `UtteranceEnd` от Deepgram + последняя фраза от системного аудио
2. **По контенту**: фраза заканчивается на `?` или начинается с вопросительных слов (как, что, почему, расскажи, объясни...)
3. **По горячей клавише**: Cmd+Shift+A — принудительный триггер

**Debounce 2 секунды** — защита от двойного срабатывания при медленной речи.

### `llm_client.py` — OpenAI Streaming

- `AsyncOpenAI` клиент с потоковой генерацией (`stream=True`)
- Две модели: `gpt-4o-mini` (быстрые ответы, <1с TTFT) и `gpt-4o` (код, Vision)
- Скользящее окно контекста — последние 5 обменов (вопрос + ответ)
- System prompt загружается из `profile.md` + `job_description.md` (кастомизация под каждое собеседование)
- При скриншоте — автоматическое переключение на `gpt-4o` с Vision

### `context_manager.py` — Управление контекстом

- Полная история транскрипции для справки
- Скользящее окно последних 5 обменов для LLM
- Каждый обмен: вопрос + ответ + timestamp + источник (audio/screenshot)

---

## Stealth-фичи Electron

Overlay спроектирован для максимальной незаметности:

| Фича | API | Эффект |
|---|---|---|
| Невидимость при screen share | `setContentProtection(true)` | Окно не захватывается при демонстрации экрана |
| Поверх всех окон | `setAlwaysOnTop(true, "screen-saver")` | Выше даже fullscreen-приложений |
| Click-through | `setIgnoreMouseEvents(true, {forward: true})` | Клики проходят сквозь overlay к окну под ним |
| Нет иконки в Dock | `app.dock.hide()` | Незаметно в панели приложений |
| Нет в taskbar | `skipTaskbar: true` | Не отображается в переключателе окон |
| Все рабочие столы | `setVisibleOnAllWorkspaces(true)` | Виден на всех Spaces и в fullscreen |
| Прозрачное окно | `transparent: true, frame: false` | Безрамочное, с контролируемой прозрачностью |
| Обфускация имени | `app.setName("System Helper")` | В Activity Monitor выглядит как системный процесс |

### Click-through механизм

По умолчанию overlay пропускает все клики. При наведении мыши на интерактивный элемент (кнопка, скролл) — компонент `<Interactable>` через IPC вызывает `setIgnoreMouseEvents(false)`, при уходе мыши — обратно `true`. Это позволяет взаимодействовать с overlay не блокируя работу в Zoom.

---

## Горячие клавиши

| Комбинация | Действие |
|---|---|
| `Cmd+Shift+\` | Показать / скрыть overlay |
| `Cmd+Shift+M` | Начать / остановить запись |
| `Cmd+Shift+A` | Принудительная генерация ответа |
| `Cmd+Shift+S` | Скриншот → анализ GPT-4o Vision |
| `Cmd+Shift+C` | Скопировать последний ответ |
| `Cmd+Shift+Up` | Увеличить прозрачность (+10%) |
| `Cmd+Shift+Down` | Уменьшить прозрачность (-10%) |

Все горячие клавиши работают глобально — даже когда Zoom/Meet в фокусе.

---

## SSE события (бэкенд → фронтенд)

| Событие | Данные | Описание |
|---|---|---|
| `transcript` | `{source, speaker, text}` | Транскрипция в реальном времени |
| `question_detected` | `{text}` | Обнаружен вопрос интервьюера |
| `ai_answer_start` | `{question, id}` | Начало генерации ответа |
| `ai_answer_chunk` | `{text, id}` | Фрагмент ответа (streaming) |
| `ai_answer_end` | `{full_answer, id}` | Генерация завершена |
| `status` | `{type, message}` | Статусы: recording, stopped, error |
| `ping` | `""` | Keepalive каждые 30с |

---

## HTTP API

| Метод | Endpoint | Описание |
|---|---|---|
| `GET` | `/health` | Проверка работоспособности бэкенда |
| `GET` | `/stream` | SSE стрим событий |
| `GET` | `/transcript` | Полный лог транскрипции |
| `GET` | `/status` | Текущее состояние (запись, ключи, счётчики) |
| `POST` | `/start` | Начать запись и транскрипцию |
| `POST` | `/stop` | Остановить запись |
| `POST` | `/screenshot` | Скриншот + анализ AI |
| `POST` | `/force-answer` | Принудительная генерация ответа |

---

## Управление процессами

### Electron → Python Backend

Electron main process спавнит Python бэкенд как child process:

1. **Запуск**: `spawn(python3, [main.py])` с наследованием env
2. **Health polling**: цикл `fetch(/health)` каждые 200мс, до 50 попыток (10с)
3. **Auto-restart**: при крэше Python (exit code != 0) — перезапуск через 2с
4. **Graceful shutdown**: `SIGTERM` при закрытии Electron

### dev.sh — Однокомандный запуск

Скрипт `scripts/dev.sh`:
1. Запускает Python бэкенд в фоне
2. Ждёт `/health` ответ
3. Запускает Electron overlay
4. `trap cleanup EXIT` — убивает оба процесса при Ctrl+C

---

## Структура проекта

```
AxelAiAssistant/
├── backend/
│   ├── main.py              # Точка входа, FastAPI app, связка модулей
│   ├── config.py            # Конфигурация, загрузка .env
│   ├── audio_capture.py     # Dual audio capture (mic + BlackHole)
│   ├── transcription.py     # Deepgram WebSocket клиент
│   ├── question_detector.py # Детекция вопросов (heuristics + debounce)
│   ├── llm_client.py        # OpenAI GPT-4o streaming
│   ├── screenshot.py        # Захват экрана (Pillow)
│   ├── context_manager.py   # История разговора
│   ├── routes.py            # SSE queue + emit_event утилита
│   ├── requirements.txt     # Python зависимости
│   ├── profile.md           # Профиль кандидата (кастомизация)
│   └── job_description.md   # Описание вакансии (кастомизация)
│
├── overlay/
│   ├── electron.vite.config.ts  # Конфиг electron-vite
│   ├── package.json
│   ├── postcss.config.cjs
│   ├── tailwind.config.cjs
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   └── src/
│       ├── index.html
│       ├── main.tsx
│       ├── main/
│       │   ├── index.ts         # Electron main process
│       │   └── child_process.ts # Python lifecycle
│       ├── preload/
│       │   └── index.ts         # IPC bridge
│       ├── components/
│       │   ├── Overlay.tsx      # Ответы AI с Markdown
│       │   ├── Transcript.tsx   # Панель транскрипции
│       │   ├── StatusBar.tsx    # Индикаторы + drag zone
│       │   ├── Controls.tsx     # Кнопки управления
│       │   └── Interactable.tsx # Click-through wrapper
│       ├── hooks/
│       │   ├── useSSE.ts        # EventSource + auto-reconnect
│       │   └── useHotkeys.ts    # IPC hotkey bridge
│       ├── styles/
│       │   └── globals.css      # Tailwind + кастомные стили
│       └── types/
│           └── electron.d.ts    # Типы window.electronAPI
│
├── scripts/
│   ├── setup.sh             # Установка зависимостей
│   └── dev.sh               # Запуск в dev-режиме
│
├── docs/
│   ├── ARCHITECTURE.md      # Этот файл
│   └── BUGFIX_NOTES.md      # Заметки по отладке
│
├── .env.example             # Шаблон API ключей
├── README.md                # Документация (EN)
└── README.ru.md             # Документация (RU)
```
