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
