#!/bin/bash

# Ensure we are in the script's directory
cd "$(dirname "$0")"

if [ ! -x ".venv-pyside/bin/python" ]; then
    echo "[ERROR] Virtual environment not found."
    echo "Please create the isolated PySide6 environment first."
    exit 1
fi

echo "[Launcher] Activating environment..."
source .venv-pyside/bin/activate

if [ "${REALTIME_TON_DEV_RELOAD:-0}" = "1" ]; then
    echo "[Launcher] Starting development hot-reload mode..."
    exec python reloader.py
fi

echo "[Launcher] Starting dashboard..."
exec python dashboard.py
