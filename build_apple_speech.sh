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

echo "Built Apple speech, translation, and system-audio helpers"
