#!/bin/bash
set -e

echo "=== Interview Assistant Setup ==="

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    echo "Error: Homebrew is required. Install from https://brew.sh"
    exit 1
fi

# Install system dependencies
echo "Installing portaudio (required for sounddevice)..."
brew install portaudio 2>/dev/null || echo "portaudio already installed"

echo "Installing BlackHole 2ch (virtual audio driver)..."
brew install blackhole-2ch 2>/dev/null || echo "blackhole-2ch already installed"

# Python backend setup
echo ""
echo "=== Setting up Python backend ==="
cd "$(dirname "$0")/../backend"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Created virtual environment"
fi

source .venv/bin/activate
pip install -r requirements.txt
echo "Python dependencies installed"

# Overlay setup
echo ""
echo "=== Setting up Electron overlay ==="
cd ../overlay
npm install
echo "Node dependencies installed"

# Check for .env
cd ..
if [ ! -f ".env" ]; then
    echo ""
    echo "WARNING: .env file not found!"
    echo "Copy .env.example to .env and fill in your API keys:"
    echo "  cp .env.example .env"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "1. Configure Multi-Output Device in Audio MIDI Setup (BlackHole + Built-in Output)"
echo "2. Create .env with your API keys"
echo "3. Run: ./scripts/dev.sh"
