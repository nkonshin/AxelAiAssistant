#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Start CLIProxyAPI for Claude Max (if installed and not already running)
CLIPROXY_PID=""
if command -v cliproxyapi &>/dev/null; then
    if ! curl -s http://localhost:8317/v1/models > /dev/null 2>&1; then
        echo "Starting CLIProxyAPI..."
        cliproxyapi > /dev/null 2>&1 &
        CLIPROXY_PID=$!
        sleep 1
        if curl -s http://localhost:8317/v1/models > /dev/null 2>&1; then
            echo "CLIProxyAPI is ready (Claude Max)"
        else
            echo "Warning: CLIProxyAPI failed to start — Claude provider won't work"
        fi
    else
        echo "CLIProxyAPI already running"
    fi
else
    echo "CLIProxyAPI not installed — Claude provider unavailable (brew install cliproxyapi)"
fi

# Start Python backend
echo "Starting Python backend..."
cd "$PROJECT_DIR/backend"
source .venv/bin/activate 2>/dev/null || true
python3 main.py &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in $(seq 1 50); do
    if curl -s http://127.0.0.1:8765/health > /dev/null 2>&1; then
        echo "Backend is ready"
        break
    fi
    if [ $i -eq 50 ]; then
        echo "Error: Backend failed to start"
        kill $BACKEND_PID 2>/dev/null
        exit 1
    fi
    sleep 0.2
done

# Start Electron overlay
# Unset ELECTRON_RUN_AS_NODE — some tools set this, which breaks Electron
echo "Starting Electron overlay..."
cd "$PROJECT_DIR/overlay"
unset ELECTRON_RUN_AS_NODE
npm run dev &
OVERLAY_PID=$!

# Cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $OVERLAY_PID 2>/dev/null
    kill $BACKEND_PID 2>/dev/null
    [ -n "$CLIPROXY_PID" ] && kill $CLIPROXY_PID 2>/dev/null
    wait 2>/dev/null
    echo "Done"
}
trap cleanup EXIT INT TERM

echo ""
echo "=== Interview Assistant is running ==="
echo "Backend:  http://127.0.0.1:8765"
[ -n "$CLIPROXY_PID" ] && echo "Claude:   http://localhost:8317 (CLIProxyAPI)"
echo "Press Ctrl+C to stop"
echo ""

# Wait for either process to exit
wait
