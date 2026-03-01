# Заметки по отладке — Bugfix Session

## Контекст

После завершения основной разработки (8 коммитов: от scaffolding до README) пришло время первого тестового запуска. Ожидание было простым: `npm run dev` в папке overlay — и приложение запустится. Реальность оказалась интереснее.

---

## Проблема 1: electron-vite не находит entry point

### Симптом

```
ERROR  An entry point is required in the electron vite main config
```

Приложение отказывалось собираться. electron-vite не мог найти точку входа для main process.

### Причина

Дефис вместо точки в имени конфига. Файл был назван `electron-vite.config.ts`, а electron-vite ищет строго `electron.vite.config.ts`.

Одна точка вместо дефиса — и сборщик полностью игнорирует конфигурацию.

### Параллельная проблема

electron-vite по умолчанию ожидает определённую структуру файлов:
- `src/main/index.ts` — main process
- `src/preload/index.ts` — preload script

А в проекте файлы лежали в `overlay/electron/`:
- `electron/main.ts`
- `electron/preload.ts`
- `electron/child_process.ts`

### Решение

1. Переименован конфиг: `electron-vite.config.ts` → `electron.vite.config.ts`
2. Перенесены исходники:
   - `electron/main.ts` → `src/main/index.ts`
   - `electron/preload.ts` → `src/preload/index.ts`
   - `electron/child_process.ts` → `src/main/child_process.ts`
3. Обновлён импорт: `from './child_process'` → `from './child_process.js'` (ESM)
4. Добавлен `externalizeDepsPlugin()` в конфиг main и preload — без него electron-vite пытался бандлить сам Electron, что ломало require('electron')

---

## Проблема 2: ESM vs CommonJS конфликт конфигов

### Симптом

```
warning: To load an ES module, set "type": "module" in the package.json
```

PostCSS и Tailwind конфиги использовали `export default` (ESM синтаксис), но electron-vite ожидал CommonJS.

### Решение

Переименованы файлы с `.js` на `.cjs` и заменён синтаксис:

```javascript
// Было (ESM):
export default { ... }

// Стало (CommonJS):
module.exports = { ... }
```

- `postcss.config.js` → `postcss.config.cjs`
- `tailwind.config.js` → `tailwind.config.cjs`

---

## Проблема 3: Electron запускается как обычный Node.js

### Симптом

```
TypeError: Cannot read properties of undefined (reading 'whenReady')
```

`app` из `require('electron')` оказывался `undefined`. При этом Electron был корректно установлен, бинарник на месте (232MB фреймворк в `Frameworks/`).

### Расследование

Это была самая неочевидная проблема из трёх. Первоначальные гипотезы:

1. **Electron бинарник повреждён?** — Нет, 49KB launcher stub + 232MB Frameworks/ — нормальная структура macOS app bundle
2. **externalizeDepsPlugin не работает?** — Добавлен, проверен, работает
3. **Конфликт версий?** — `electron@28.3.3` корректно установлен

Разгадка нашлась в переменной окружения. Оказалось, в среде был установлен:

```
ELECTRON_RUN_AS_NODE=1
```

Эта переменная — документированная фича Electron. Когда она установлена, `electron` запускается **как обычный Node.js процесс**, без инициализации Chromium, без создания `app`, `BrowserWindow` и всего остального Electron API. Именно поэтому `require('electron').app` возвращал `undefined`.

Переменную устанавливают некоторые инструменты разработки (IDE, CLI-утилиты), которые используют Electron-бинарник как Node.js runtime.

### Решение

1. В `scripts/dev.sh` добавлен `unset ELECTRON_RUN_AS_NODE` перед запуском Electron
2. В `child_process.ts` добавлена очистка env при спавне Python бэкенда:

```typescript
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE
```

### Проверка

```bash
env -u ELECTRON_RUN_AS_NODE npm run dev
```

Electron стартовал, окно создалось, Python бэкенд поднялся, health endpoint отвечает.

---

## Бонус: Deprecation warning в FastAPI

### Симптом

```
DeprecationWarning: on_event is deprecated, use lifespan event handlers instead.
```

### Решение

Заменён устаревший паттерн:

```python
# Было:
@app.on_event("startup")
async def startup_event(): ...

@app.on_event("shutdown")
async def shutdown_event(): ...

# Стало:
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown

app = FastAPI(lifespan=lifespan)
```

Заодно упрощён `routes.py` — из него убраны определения FastAPI app и роутов. Он теперь содержит только `sse_queue` и `emit_event()`, а все эндпоинты живут в `main.py`.

---

## Итого: что было исправлено

| Файл | Изменение |
|---|---|
| `electron-vite.config.ts` → `electron.vite.config.ts` | Правильное имя конфига |
| `electron/*.ts` → `src/main/*.ts`, `src/preload/*.ts` | Структура каталогов electron-vite |
| `postcss.config.js` → `.cjs` | CommonJS совместимость |
| `tailwind.config.js` → `.cjs` | CommonJS совместимость |
| `electron.vite.config.ts` | Добавлен `externalizeDepsPlugin`, `__dirname`, input paths |
| `scripts/dev.sh` | `unset ELECTRON_RUN_AS_NODE` |
| `src/main/child_process.ts` | `delete env.ELECTRON_RUN_AS_NODE` |
| `backend/main.py` | `lifespan` вместо `on_event`, все роуты в одном файле |
| `backend/routes.py` | Упрощён до SSE queue + emit |

### Ключевой урок

Самая коварная ошибка — `ELECTRON_RUN_AS_NODE=1`. Она не выдаёт понятного сообщения, не логируется, и заставляет Electron молча работать как обычный Node.js. Если `require('electron').app === undefined` — первым делом проверяй переменные окружения.

---

## Session 2: Полный редизайн UI + фикс click-through

### Контекст

После первого успешного запуска стало очевидно, что UI нуждается в серьёзной переработке. Главная жалоба — **окно оверлея было полностью некликабельным**: нельзя перетащить, нажать кнопку, ввести текст.

---

## Проблема 4: Окно не реагирует на клики и перетаскивание

### Симптом

Overlay появляется на экране, контент отображается корректно, но:
- Нельзя перетащить окно мышкой
- Нельзя нажать ни на одну кнопку
- Мышь проходит «сквозь» окно к приложениям за ним

### Причина

В `src/main/index.ts` при создании окна стоял вызов:

```typescript
mainWindow.setIgnoreMouseEvents(true, { forward: true })
```

Это включало режим **click-through по умолчанию** — все mouse events перенаправлялись на приложения под оверлеем. Задумка была правильной (невидимый ассистент не должен мешать), но реализация была слишком агрессивной: у пользователя не было способа взаимодействовать с самим оверлеем.

### Решение

1. **Убран `setIgnoreMouseEvents` из `createWindow()`** — окно теперь интерактивно по умолчанию
2. **Click-through стал opt-in**: добавлен IPC хэндлер `set-click-through`, который включает/выключает прозрачность для кликов через тогл в настройках
3. **Drag zone**: верхняя панель (TopBar) получила CSS-свойство `-webkit-app-region: drag`, а кнопки внутри неё — `no-drag`, что позволяет перетаскивать окно за шапку

```typescript
// IPC handler в main process
ipcMain.on('set-click-through', (_event, enabled: boolean) => {
  if (mainWindow) {
    mainWindow.setIgnoreMouseEvents(enabled, { forward: true })
  }
})
```

4. **Умный click-through при открытых настройках**: когда пользователь открывает SettingsPanel, click-through автоматически отключается (даже если был включён), а при закрытии — восстанавливается предыдущее состояние

---

## Редизайн: от прототипа к полноценному UI

### Что было

Минималистичный набор компонентов без единого дизайн-языка:
- `Overlay.tsx` — отображение ответа AI
- `StatusBar.tsx` — индикаторы статуса
- `Transcript.tsx` — панель транскрипции
- `Controls.tsx` — кнопки управления

### Что стало

Полный редизайн в стиле **glassmorphism** с тёмной полупрозрачной палитрой:

| Компонент | Описание |
|---|---|
| `TopBar.tsx` | Drag-зона с SVG-логотипом, анимированными точками записи, кнопками действий и меню настроек |
| `InputBar.tsx` | Поле ручного ввода вопроса (POST /ask) |
| `AnswerView.tsx` | Основная область: вопрос → ответ с markdown/code highlighting, мигающий курсор при стриминге |
| `AnswerNav.tsx` | Навигация по истории ответов: ←/→, счётчик страниц, кнопка копирования |
| `SettingsPanel.tsx` | Полноэкранная панель настроек: запись, прозрачность, автоответы, click-through, горячие клавиши, выход |

### Дизайн-система

CSS полностью переписан с custom properties:

```css
:root {
  --bg-base: rgba(18, 18, 24, 0.88);
  --bg-surface: rgba(255, 255, 255, 0.04);
  --accent: #6e7bf2;
  --accent-green: #34d399;
  --accent-amber: #f59e0b;
  --accent-red: #ff453a;
  --border: rgba(255, 255, 255, 0.06);
}
```

- Шрифты: **DM Sans** (UI) + **JetBrains Mono** (код) — подключены через Google Fonts CDN
- Фон: `backdrop-filter: blur(24px) saturate(1.4)` — стекломорфный эффект
- Анимации: пульсирующие точки записи (`dot-pulse`), мигающий курсор стриминга, slide-in настроек

### Новые IPC-каналы

| Канал | Направление | Назначение |
|---|---|
| `quit-app` | Renderer → Main | Закрыть приложение |
| `set-opacity` | Renderer → Main | Установить прозрачность окна (0.2–1.0) |
| `set-click-through` | Renderer → Main | Вкл/выкл click-through |

### Новый бэкенд-эндпоинт

```
POST /ask  { "question": "текст" }
```

Позволяет задать вопрос вручную через InputBar, не дожидаясь аудио-детекции. Вопрос проходит тот же pipeline: `on_question_detected` → LLM → SSE → UI.

### Новые горячие клавиши

| Комбинация | Действие |
|---|---|
| `Cmd+←` | Предыдущий ответ |
| `Cmd+→` | Следующий ответ |

Добавлены поверх существующих `Cmd+Shift+*` комбинаций.

### История ответов

`useSSE` полностью переписан: вместо единичного `currentAnswer` теперь хранится массив `AnswerEntry[]` с навигацией:

```typescript
interface AnswerEntry {
  question: string
  answer: string
  isComplete: boolean
}
```

`viewIndex` указывает на текущий просматриваемый ответ. Методы `goNext()`, `goPrev()`, `goToLatest()` позволяют листать историю.

### Фикс утечки IPC-слушателей

В `useHotkeys` обнаружена проблема: каждый рендер добавлял новый listener на `hotkey-action` без удаления старого. Решение:

```typescript
onHotkeyAction: (callback) => {
  ipcRenderer.removeAllListeners('hotkey-action')
  ipcRenderer.on('hotkey-action', (_event, action) => callback(action))
}
```

---

## Итого: Session 2

| Файл | Изменение |
|---|---|
| `src/main/index.ts` | Убран default click-through, добавлены IPC: quit/opacity/click-through, Cmd+←/→ |
| `src/preload/index.ts` | 3 новых метода + removeAllListeners фикс |
| `src/types/electron.d.ts` | Расширен ElectronAPI: quitApp, setOpacity, setClickThrough |
| `src/styles/globals.css` | Полный редизайн: glassmorphism, анимации, markdown-стили |
| `src/components/TopBar.tsx` | Новый — drag-зона, лого, кнопки |
| `src/components/InputBar.tsx` | Новый — ручной ввод вопросов |
| `src/components/AnswerView.tsx` | Новый — markdown-рендер ответов |
| `src/components/AnswerNav.tsx` | Новый — навигация по истории |
| `src/components/SettingsPanel.tsx` | Новый — настройки, тогглы, горячие клавиши |
| `src/hooks/useSSE.ts` | Переписан: AnswerEntry[], навигация |
| `src/hooks/useHotkeys.ts` | Переписан: map action→handler |
| `src/App.tsx` | Полная переработка с новой архитектурой компонентов |
| `src/index.html` | DM Sans + JetBrains Mono fonts |
| `backend/main.py` | POST /ask endpoint |

### Ключевой урок

`setIgnoreMouseEvents(true)` — мощный инструмент stealth-режима, но его нельзя включать по умолчанию без механизма переключения. Пользователь должен иметь возможность взаимодействовать с оверлеем «из коробки», а click-through — это opt-in фича для моментов, когда нужна полная прозрачность.

---

## Session 3: Multi-provider LLM + улучшение читаемости горячих клавиш

### Контекст

Добавлена возможность использовать Claude через подписку Max (CLIProxyAPI) как альтернативу OpenAI API. Также исправлена плохая читаемость хоткеев в UI.

---

## Фича: Мульти-провайдер LLM (OpenAI + Claude Max)

### Мотивация

У пользователя есть подписка Claude Max, и он хочет использовать модели Claude (Opus/Sonnet/Haiku) без покупки API-ключа. Anthropic не предоставляет официальный API-доступ через Max подписку, но существует неофициальный инструмент **CLIProxyAPI** — Go-бинарник, который проксирует OAuth-авторизацию Max подписки и выставляет OpenAI-совместимый endpoint на `localhost:8317/v1`.

### Реализация

**Бэкенд:**

- `config.py` — новые настройки: `LLM_PROVIDER` ("openai"/"claude"), `LLM_MODEL`, `CLI_PROXY_URL`, списки доступных моделей для каждого провайдера (`OPENAI_MODELS`, `CLAUDE_MODELS`, `CLAUDE_MODEL_LABELS`)
- `llm_client.py` — полная переработка: два клиента `AsyncOpenAI` (один для OpenAI API, один для CLIProxyAPI с `base_url` и `api_key="not-needed"`), метод `set_provider()` для переключения на лету, автоматический выбор vision-модели по провайдеру
- `main.py` — новые эндпоинты `GET /settings/llm` и `POST /settings/llm` для чтения и изменения провайдера/модели в runtime

**Фронтенд:**

- `SettingsPanel.tsx` — новая секция "LLM Provider & Model": chips для выбора провайдера (OpenAI / Claude Max) и модели, fetch настроек с бэкенда при открытии панели, мгновенное применение через POST

**Конфигурация:**

- `.env.example` — документация новых переменных (`LLM_PROVIDER`, `LLM_MODEL`, `CLI_PROXY_URL`)

| Файл | Изменение |
|---|---|
| `backend/config.py` | Мульти-провайдер настройки, списки моделей |
| `backend/llm_client.py` | Два AsyncOpenAI клиента, set_provider(), _get_vision_model() |
| `backend/main.py` | GET/POST /settings/llm, обновлённая инициализация |
| `overlay/src/components/SettingsPanel.tsx` | UI выбора провайдера и модели |
| `.env.example` | Документация новых env-переменных |

---

## Фикс: Плохая читаемость горячих клавиш в UI

### Симптом

На кнопках «Спросить» и «Скриншот» и в empty state подсказке хоткеи были почти нечитаемы — слишком маленький шрифт, низкая непрозрачность и тёмный цвет на тёмном фоне.

### Причина

- `.action-btn .shortcut`: font-size 10px, opacity 0.5
- `.kbd`: color `var(--text-tertiary)` (#48484a) — слишком тёмный на фоне `rgba(10, 10, 14, 0.92)`

### Решение

- `.shortcut`: размер 10→11px, opacity 0.5→0.7, добавлен явный `color: var(--text-secondary)`
- `.kbd`: цвет `--text-tertiary`→`--text-secondary` (#8e8e93), размер 10→11px, усилен фон и бордер

| Файл | Изменение |
|---|---|
| `overlay/src/styles/globals.css` | Улучшена видимость хоткеев + добавлены стили `.setting-chip` |
