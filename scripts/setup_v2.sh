#!/bin/bash
# Установка v2: audiotee (захват системного звука), зависимости Python, сборка Electron.
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AXEL_HOME="$HOME/.axel-assistant"
mkdir -p "$AXEL_HOME/bin" "$AXEL_HOME/src"

echo "== audiotee (Core Audio tap) =="
if [ ! -x "$AXEL_HOME/bin/audiotee" ]; then
  cd "$AXEL_HOME/src"
  [ -d audiotee ] || git clone -q --depth 1 https://github.com/makeusabrew/audiotee.git
  cd audiotee && swift build -c release
  cp .build/release/audiotee "$AXEL_HOME/bin/"
fi
echo "ok: $AXEL_HOME/bin/audiotee"

echo "== Python =="
cd "$PROJECT_DIR/backend"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

echo "== Electron =="
cd "$PROJECT_DIR/overlay"
[ -d node_modules ] || npm install
unset ELECTRON_RUN_AS_NODE
npx electron-vite build >/dev/null
echo "Готово. Запуск: scripts/start_v2.sh"
