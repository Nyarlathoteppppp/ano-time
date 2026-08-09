#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p .build

xcrun swiftc \
  -parse-as-library \
  -O \
  -target arm64-apple-macosx26.0 \
  apple_speech_helper.swift \
  -o .build/apple_speech_helper

xcrun swiftc \
  -parse-as-library \
  -O \
  -target arm64-apple-macosx26.0 \
  apple_translation_helper.swift \
  -o .build/apple_translation_helper

xcrun swiftc \
  -parse-as-library \
  -O \
  -target arm64-apple-macosx26.0 \
  apple_system_audio_helper.swift \
  -o .build/apple_system_audio_helper

# Package the ScreenCaptureKit process as a real application. TCC grants
# capture permission to the executable that calls ScreenCaptureKit; a loose
# ad-hoc binary has no stable app identity and cannot be managed reliably in
# System Settings.
AUDIO_APP=".build/Realtime Translator Audio.app"
AUDIO_MACOS="$AUDIO_APP/Contents/MacOS"
mkdir -p "$AUDIO_MACOS"
cp .build/apple_system_audio_helper "$AUDIO_MACOS/RealtimeTranslatorAudio"
cp native_audio_helper_Info.plist "$AUDIO_APP/Contents/Info.plist"
/usr/bin/codesign --force --deep --sign - \
  --identifier "com.nyarlathotep.realtime-ton.audio" "$AUDIO_APP"

echo "Built Apple speech, translation, and system-audio helpers"
