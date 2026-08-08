#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

APP_PATH="$HOME/Desktop/Realtime Translator.app"
/usr/bin/osacompile -o "$APP_PATH" desktop_launcher.applescript

PLIST="$APP_PATH/Contents/Info.plist"
BUNDLE_ID="com.nyarlathotep.realtime-ton"

set_plist_string() {
    local key="$1"
    local value="$2"
    /usr/libexec/PlistBuddy -c "Set :$key $value" "$PLIST" 2>/dev/null || \
        /usr/libexec/PlistBuddy -c "Add :$key string $value" "$PLIST"
}

# ScreenCaptureKit/TCC needs a stable application identity. The AppleScript app
# produced by osacompile has no bundle identifier by default, which leaves stale
# permission rows after the launcher is rebuilt.
set_plist_string "CFBundleIdentifier" "$BUNDLE_ID"
set_plist_string \
    "NSScreenCaptureUsageDescription" \
    "Realtime Translator captures screen-associated system audio for live subtitles."
set_plist_string \
    "NSAudioCaptureUsageDescription" \
    "Realtime Translator captures audio from videos and applications for live translation."

/usr/bin/codesign --force --deep --sign - --identifier "$BUNDLE_ID" "$APP_PATH"

echo "Installed: $APP_PATH"
echo "Bundle ID: $BUNDLE_ID"
