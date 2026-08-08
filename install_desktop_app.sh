#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

APP_PATH="$HOME/Desktop/Realtime Translator.app"
/usr/bin/osacompile -o "$APP_PATH" desktop_launcher.applescript

echo "Installed: $APP_PATH"
