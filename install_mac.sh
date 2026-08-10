#!/bin/bash

# ==================================================
# Real-Time Translator - macOS Installation Script
# ==================================================
# This script automates the setup process for the Real-Time Translator.
# It will:
#   1. Verify Python 3 is installed
#   2. Create a virtual environment for isolated dependencies
#   3. Install all required Python packages
#   4. Install Apple Silicon optimizations (if applicable)
#   5. Check for required system tools (ffmpeg)
#   6. Explain the optional legacy BlackHole path
#   7. Check for optional audio management tools

echo "==================================================="
echo "  Real-Time Translator - macOS Installer"
echo "==================================================="

# ==================================================
# Step 1: Verify Python 3 Installation
# ==================================================
# Python 3.8+ is required to run this application.
# If not found, the script will exit with an error message.
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed."
    echo "Please install it via brew: brew install python"
    exit 1
fi

# ==================================================
# Step 2: Create Virtual Environment
# ==================================================
# A virtual environment (.venv) isolates Python packages from your system,
# preventing conflicts with other projects. If .venv already exists,
# we'll skip this step and reuse the existing environment.
if [ ! -d ".venv" ]; then
    echo "[1/4] Creating virtual environment (.venv)..."
    python3 -m venv .venv
else
    echo "[1/4] Virtual environment exists."
fi

# ==================================================
# Step 3: Install Python Dependencies
# ==================================================
# Activates the virtual environment and installs all required packages
# from requirements.txt, including:
#   - PyQt6 (GUI framework)
#   - faster-whisper (speech recognition)
#   - funasr (Alibaba ASR engine)
#   - sounddevice (audio capture)
#   - openai (translation API)
#   - And other essential libraries
echo "[2/4] Installing dependencies..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# ==================================================
# Step 4: Apple Silicon GPU Optimization
# ==================================================
# If running on Apple Silicon (M1/M2/M3/M4), install mlx-whisper
# to enable Metal GPU acceleration for Whisper models.
# This provides significantly faster transcription compared to CPU.
# Intel Macs will use the standard faster-whisper backend.
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    echo "[3/4] Apple Silicon (M1/M2/M3) detected!"
    echo "      Installing mlx-whisper for Metal GPU acceleration..."
    pip install mlx-whisper
else
    echo "[3/4] Intel Mac detected. Using standard larger models."
fi

# ==================================================
# Step 5: Check System Dependencies
# ==================================================
# FFmpeg is required for audio processing and format conversion.
# It's used internally by the speech recognition engines.
# If missing, the script will warn you but continue installation.
echo "[4/5] Checking system tools..."
MISSING_TOOLS=0

if ! command -v ffmpeg &> /dev/null; then
    echo "  [WARNING] ffmpeg is MISSING."
    echo "  -> Run: brew install ffmpeg"
    MISSING_TOOLS=1
else
    echo "  [OK] ffmpeg found."
fi

if [ $MISSING_TOOLS -eq 1 ]; then
    echo ""
    echo "Please install the missing tools above manually."
fi

# ==================================================
# Step 6: Optional Legacy BlackHole Path
# ==================================================
# Anotime captures videos/apps through native ScreenCaptureKit and does not
# require BlackHole. Keep this check only for users of the legacy audio route.
echo "[5/5] Checking optional legacy audio tools..."
if [ -d "/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver" ]; then
    echo "  [INFO] BlackHole found (optional legacy route)."
else
    echo "  [OK] BlackHole is not installed; native ScreenCaptureKit system audio is supported."
fi

# ==================================================
# Step 7: Check Optional Tools
# ==================================================
# SwitchAudioSource (optional) allows the dashboard to programmatically
# switch audio devices. This is convenient but not required.
# Without it, you'll need to manually change audio settings in macOS.
#
# Installation: brew install switchaudio-osx
if command -v SwitchAudioSource &> /dev/null; then
    echo "  [OK] SwitchAudioSource found (for device management)."
else
    echo "  [INFO] SwitchAudioSource not found (optional)."
    echo "  -> Install for better device management: brew install switchaudio-osx"
    echo "  -> This enables programmatic audio device switching in the dashboard."
    echo ""
fi

if command -v swift &> /dev/null; then
    echo "[Native UI] Building DynamicNotchKit subtitle helper..."
    chmod +x build_native_notch.sh
    ./build_native_notch.sh
else
    echo "[WARNING] Swift compiler not found; Physical MacBook Notch mode cannot be built."
    echo "  -> Install Xcode Command Line Tools: xcode-select --install"
fi

# Apple SpeechAnalyzer and the persistent Apple Translation helper used by
# Anotime require the macOS 26 SDK/runtime. Build them during installation so
# users see compatibility errors here instead of a silent missing draft later.
MACOS_MAJOR=$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)
if [ "$ARCH" != "arm64" ]; then
    echo "[Apple Native] Apple Speech/Translation fast path requires Apple Silicon."
elif [ -n "$MACOS_MAJOR" ] && [ "$MACOS_MAJOR" -lt 26 ]; then
    echo "[Apple Native] macOS 26+ is required for Apple Speech/Translation."
    echo "  -> Use MLX/Whisper ASR and a remote translation workflow on this Mac."
elif command -v xcrun &> /dev/null; then
    echo "[Apple Native] Building Apple Speech/Translation helpers..."
    chmod +x build_apple_speech.sh
    if ! ./build_apple_speech.sh; then
        echo "[WARNING] Apple native helpers could not be built."
        echo "  -> Install/update Xcode Command Line Tools, then rerun this installer."
    fi
else
    echo "[WARNING] xcrun is missing; Apple Speech/Translation cannot be built."
    echo "  -> Run: xcode-select --install"
fi

echo ""
echo "==================================================="
echo "  Installation Complete!"
echo "  Run './start_mac.sh' to launch."
echo "==================================================="
