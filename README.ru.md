# Axel AI Assistant

AI-ассистент для собеседований на macOS в реальном времени. Слушает аудио собеседования (микрофон + голос интервьюера из Zoom/Teams/Meet), транскрибирует речь, детектирует вопросы и генерирует ответы в невидимом overlay поверх экрана.

## Архитектура

```
┌─────────────────────────────────────────┐
│        Electron Overlay (React)          │
│  Прозрачный, always-on-top, stealth     │
│  Защита контента (скрыт при шаринге)    │
└──────────┬────────────────┬─────────────┘
           │ SSE            │ HTTP
           ▼                ▼
┌─────────────────────────────────────────┐
│        Python Backend (FastAPI)           │
│  Захват аудио → Deepgram → GPT-4o       │
│  Детекция вопросов → Стриминг ответов   │
└─────────────────────────────────────────┘
```

## Требования

- macOS 13+
- Python 3.11+
- Node.js 18+
- [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole) — виртуальный аудио-драйвер
- portaudio

```bash
brew install blackhole-2ch portaudio node
```

## Настройка BlackHole (обязательно)

1. Откройте **Audio MIDI Setup** (Spotlight → "Audio MIDI Setup")
2. Нажмите **"+"** → **Create Multi-Output Device**
3. Отметьте: **Built-in Output** + **BlackHole 2ch**
4. Правый клик → **Use This Device For Sound Output**
5. Проверьте: звук должен играть нормально через динамики

## Установка

```bash
# Клонировать репозиторий
git clone https://github.com/nkonshin/AxelAiAssistant.git
cd AxelAiAssistant

# Создать .env с API ключами
cp .env.example .env
# Отредактировать .env и вписать ключи

# Запустить установку (все зависимости)
./scripts/setup.sh
```

## Запуск

```bash
# Запуск всего (бэкенд + overlay)
./scripts/dev.sh
```

Или вручную:

```bash
# Терминал 1: Python бэкенд
cd backend && source .venv/bin/activate && python main.py

# Терминал 2: Electron overlay
cd overlay && npm run dev
```

## Горячие клавиши

| Комбинация | Действие |
|---|---|
| `Cmd+Shift+\` | Показать / скрыть overlay |
| `Cmd+Shift+M` | Начать / остановить запись |
| `Cmd+Shift+A` | Принудительная генерация ответа |
| `Cmd+Shift+S` | Скриншот → анализ AI |
| `Cmd+Shift+C` | Скопировать последний ответ |
| `Cmd+Shift+↑` | Увеличить прозрачность |
| `Cmd+Shift+↓` | Уменьшить прозрачность |

## API эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| GET | `/health` | Проверка здоровья |
| GET | `/stream` | SSE поток событий |
| GET | `/status` | Состояние приложения |
| GET | `/transcript` | Полный транскрипт |
| POST | `/start` | Начать запись |
| POST | `/stop` | Остановить запись |
| POST | `/screenshot` | Захват и анализ экрана |
| POST | `/force-answer` | Принудительный ответ из буфера |

## Стек технологий

- **Бэкенд**: Python, FastAPI, sounddevice, Deepgram Nova-3, OpenAI GPT-4o
- **Фронтенд**: Electron, React, TypeScript, Tailwind CSS
- **Аудио**: BlackHole 2ch для захвата системного звука

## Подготовка к собеседованию

1. Обновите `backend/profile.md` — ваш профиль и опыт
2. Обновите `backend/job_description.md` — описание вакансии
3. Убедитесь что BlackHole настроен и API ключи на месте
4. Запустите `./scripts/dev.sh` и проверьте чеклист:
   - Overlay НЕ виден при screen share в Zoom
   - BlackHole захватывает звук интервьюера
   - Deepgram распознаёт русскую речь
   - Ответ GPT-4o появляется за < 3 секунд
   - Горячие клавиши работают когда Zoom в фокусе
   - Нет иконки в Dock

## Решение проблем

**Нет звука через BlackHole**: убедитесь что Multi-Output Device выбран как выход по умолчанию в Настройки → Звук.

**Ошибка "BlackHole not found"**: установите `brew install blackhole-2ch` и перезапустите.

**Overlay виден при шаринге экрана**: проверьте что `setContentProtection(true)` активен. На macOS 15+ некоторые приложения используют ScreenCaptureKit, который может обходить защиту.

**Нет API ключей**: создайте `.env` из `.env.example` и добавьте ключи OpenAI и Deepgram.

## Лицензия

MIT
