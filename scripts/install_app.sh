#!/bin/bash
# Собрать «Notes Helper.app» (окно ассистента v2) и поставить в /Applications.
# Приложение само запускает бэкенд из ЭТОЙ папки проекта (backend/ + backend/.venv),
# поэтому правки бэкенда и ui.html пересборки не требуют — только правки overlay/src/main.
# После пересборки macOS может заново спросить разрешения (подпись ad-hoc меняется).
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Notes Helper"
DEST="/Applications"
[ -w "$DEST" ] || DEST="$HOME/Applications"
mkdir -p "$DEST" "$HOME/.axel-assistant"

echo "Собираю…"
cd "$PROJECT_DIR/overlay"
unset ELECTRON_RUN_AS_NODE
npm run app >/tmp/axel-build.log 2>&1 || { tail -30 /tmp/axel-build.log; exit 1; }
BUILT="$PROJECT_DIR/overlay/dist/mac-arm64/$APP_NAME.app"
[ -d "$BUILT" ] || { echo "Не нашёл $BUILT"; exit 1; }

# запущенную копию — закрыть
if pgrep -f "$APP_NAME.app/Contents/MacOS" >/dev/null; then
  echo "Закрываю запущенный ${APP_NAME}…"
  pkill -f "$APP_NAME.app/Contents/MacOS" || true
  sleep 2
fi

rm -rf "$DEST/$APP_NAME.app"
ditto "$BUILT" "$DEST/$APP_NAME.app"
echo "$PROJECT_DIR" > "$HOME/.axel-assistant/project_dir"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST/$APP_NAME.app" || true

# ярлык на рабочем столе
ln -sfn "$DEST/$APP_NAME.app" "$HOME/Desktop/Ассистент"

echo "Готово: $DEST/$APP_NAME.app (ярлык «Ассистент» на рабочем столе, Spotlight: Notes Helper)."
echo "Первый запуск: разреши микрофон и «Запись системного звука» для ${APP_NAME}."
