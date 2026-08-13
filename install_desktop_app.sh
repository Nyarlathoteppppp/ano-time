#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="Anotime"
APP_PATH="$HOME/Desktop/$APP_NAME.app"

# Build the native subtitle helper during installation, never when a user
# presses Launch in the control center. NativeNotchOverlay still has a
# non-blocking background-build fallback for development source updates.
echo "Preparing native subtitle helper..."
./build_native_notch.sh

/usr/bin/osacompile -o "$APP_PATH" desktop_launcher.applescript

PLIST="$APP_PATH/Contents/Info.plist"
BUNDLE_ID="com.nyarlathotep.realtime-ton"
ICON_NAME="Anotime.icns"

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
set_plist_string "CFBundleName" "$APP_NAME"
set_plist_string "CFBundleDisplayName" "$APP_NAME"
set_plist_string "CFBundleIconFile" "$ICON_NAME"
set_plist_string "CFBundleIconName" "Anotime"
set_plist_string \
    "NSScreenCaptureUsageDescription" \
    "Anotime captures screen-associated system audio for live subtitles."
set_plist_string \
    "NSAudioCaptureUsageDescription" \
    "Anotime captures audio from videos and applications for live translation."

cp "assets/$ICON_NAME" "$APP_PATH/Contents/Resources/$ICON_NAME"

/usr/bin/codesign --force --deep --sign - --identifier "$BUNDLE_ID" "$APP_PATH"
/usr/bin/touch "$APP_PATH"

echo "Installed: $APP_PATH"
echo "Bundle ID: $BUNDLE_ID"
