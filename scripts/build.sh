#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Building Axel AI Assistant ==="

cd "$PROJECT_DIR/overlay"

# Build Electron app + create .dmg
npm run dist

echo ""
echo "=== Build complete ==="
echo "Output: $PROJECT_DIR/overlay/dist/"
ls -lh "$PROJECT_DIR/overlay/dist/"*.dmg 2>/dev/null || echo "(no .dmg found — check dist/ folder)"
