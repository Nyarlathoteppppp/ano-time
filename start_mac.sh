#!/bin/bash

# Ensure we are in the script's directory
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "[ERROR] Virtual environment not found."
    echo "Please run './install_mac.sh' first."
    exit 1
fi

echo "[Launcher] Activating environment..."
source .venv/bin/activate

if [ "${REALTIME_TON_DEV_RELOAD:-0}" = "1" ]; then
    echo "[Launcher] Starting development hot-reload mode..."
    exec python reloader.py
fi

echo "[Launcher] Starting dashboard..."
exec python dashboard.py
