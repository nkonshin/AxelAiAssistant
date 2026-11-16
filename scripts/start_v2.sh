#!/bin/bash
# Запуск ассистента v2: бэкенд + окно. Закрыл окно или Ctrl+C — всё остановится.
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AXEL_HOME="$HOME/.axel-assistant"
mkdir -p "$AXEL_HOME"
LOG="$AXEL_HOME/backend.out"

printf '\033]0;Ассистент\007'
echo "Запускаю ассистента…"
lsof -ti:8765 | xargs kill 2>/dev/null; sleep 0.5

cd "$PROJECT_DIR/backend"
.venv/bin/python app.py > "$LOG" 2>&1 &
BACKEND_PID=$!
cleanup() { echo; echo "Останавливаю…"; kill $TAIL_PID $ELECTRON_PID $BACKEND_PID 2>/dev/null; wait 2>/dev/null; echo "Готово."; }
trap cleanup EXIT INT TERM

for i in $(seq 1 60); do
  curl -s http://127.0.0.1:8765/health >/dev/null && break
  if ! kill -0 $BACKEND_PID 2>/dev/null; then echo "Бэкенд упал, лог: $LOG"; tail -20 "$LOG"; exit 1; fi
  sleep 0.25
done
echo "Бэкенд работает: http://127.0.0.1:8765/ui"

cd "$PROJECT_DIR/overlay"
unset ELECTRON_RUN_AS_NODE
[ -f out/main/index.js ] || npx electron-vite build >/dev/null
npx electron . >> "$AXEL_HOME/electron.out" 2>&1 &
ELECTRON_PID=$!
sleep 3
if ! kill -0 $ELECTRON_PID 2>/dev/null; then
  echo "Окно не запустилось — открываю в браузере"
  open "http://127.0.0.1:8765/ui"
fi
echo ""
echo "Ассистент запущен. Окно — на втором мониторе."
echo "Хоткеи: ⌘⇧A ответить · ⌘⇧S скриншот · ⌘⇧1/2/3 работа · ⌘⇧M пауза · ⌘⇧\\ скрыть · ⌘⇧D другой монитор"
echo "Чтобы выключить — закрой это окно Терминала или нажми Ctrl+C."
echo ""
tail -f "$LOG" | grep --line-buffered -E "Слушаю|ERROR|WARNING|готов|Пакет" &
TAIL_PID=$!
wait $ELECTRON_PID 2>/dev/null
# окно закрыли — бэкенд оставляем, пока открыт Терминал (можно пользоваться из браузера)
echo "Окно закрыто. Интерфейс остаётся в браузере: http://127.0.0.1:8765/ui  (Ctrl+C — выключить)"
wait $BACKEND_PID
