# Real-Time Translator 🎙️➡️🇨🇳

A high-performance real-time speech-to-text and translation application built for macOS (Apple Silicon optimized).

## Features
- **⚡️ Real-Time Transcription**: Instant streaming display using `faster-whisper`, `mlx-whisper`, or `FunASR`.
- **🎯 Multiple ASR Backends**: Choose between Apple SpeechTranscriber (macOS 26 native streaming), Whisper, MLX, or FunASR.
- **🌊 Word-by-Word Streaming**: See text appear as you speak, with smart context accumulation.
- **🔄 Async Translation**: Translates text to Chinese (or target language) in the background without blocking the UI.
- **🖥️ Overlay UI**: Always-on-top, transparent, click-through window for seamless usage during meetings/videos.
- **⚙️ Hot Reloading**: Change code or config and the app restarts automatically.
- **💾 Transcript Saving**: One-click save of your session history. Can be used as subtitle or LLM analyze.
- **🪟 Resizable Glass Overlay**: Drag the overlay from its handle and resize it from the bottom-right corner.
- **◒ Notch Mode**: Switch to a compact top-center subtitle that only shows the current utterance.
- **⚡ Two-Stage Translation**: Show an Apple on-device draft first, then replace it with an LLM-refined translation.

## Demo
https://github.com/user-attachments/assets/9982fe5d-3937-42d5-bcfc-e23748c01edf

![Dashboard](./demo/main_dashboard.png)

## Installation

1. **Prerequisites**:
   - Python 3.10+
   - macOS (recommended for `mlx-whisper` support)
   - `ffmpeg` installed (e.g., `brew install ffmpeg`)
   - `BlackHole` installed (e.g., `brew install blackhole-2ch`, need to enter system password)
   - `BlackHole` Settings![BlackHole Settings](demo/how_to_set_blackhole.png)

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   
   *(Ensure you have `PyQt6`, `sounddevice`, `numpy`, `openai`, `watchdog` installed)*

   **🪟 Windows Users**:
   1. Double-click `install_windows.bat` to automatically set up the environment.
   2. Ensure [FFmpeg](https://ffmpeg.org/download.html) is installed and added to your PATH.

   **🖥 MacOS Users**:
   1. Use terminal to run `install_mac.sh`

## ✨ New Features & Quick Start
- **Modern Control Center**: Manage all settings in a dark-themed Dashboard.
- **One-Click Launch**: Start the overlay translator directly from the Dashboard.
- **Auto-Dependency Check**: Automatically installs missing requirements.
- **Audio Device Selection**: Choose your specific microphone input.

## Usage

### 1. Start the Application
Run the helper script for your OS:
- **Mac/Linux**: `./start_mac.sh`
- **Windows**: `start_windows.bat`

### 2. The Dashboard
The application opens the **Real-Time Translator Control Center**.
- **Home**: Click **"▶ Launch Translator"** to start the overlay.
- **Audio**: Select your Input Device and adjust Silence Threshold.
  * <details>
     <summary>How to Set</summary>
     1. Audio MIDI Setup: create multiple devices, including `BlackHole 2ch` device, and if you want to listen too, remember adding system output device

     ![](./demo/Audio_MIDI_Setup.png)

     2. Choose target audio device to capture

     ![](./demo/Audio_configuraiton.png)
   </details>
- **Transcription**: Choose Whisper model size (tiny, base, small, medium, large-v3, [see the difference](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages)).
  * <details>
     <summary>How to Set</summary>
     
     * MacOS
       * Whisper Model: base
       * Compute Device: audo
       * Quantization: float16
   </details>
- **Translation**: Set your OpenAI API Key and Target Language.
- **Save Settings**: Click "Save Settings" to persist your configuration.

### 3. The Overlay
Once launched, a transparent window appears:
- **Move**: Click and drag text to move.
- **Resize**: Drag the bottom-right handle (◢).
- **Stop**: Click **"⏹"** on the overlay or "Stop Translator" in the Dashboard.
- **Save**: Click **"💾 Save"** to export transcript.

## ⚙️ Configuration Reference
Settings are managed via the Dashboard, but stored in `config.ini`.

#### `[api]` Section
| Parameter | Description | Examples |
| :--- | :--- | :--- |
| `base_url` | API Endpoint | `https://api.openai.com/v1`, `http://localhost:11434/v1` |
| `api_key` | Auth Key | `sk-...` (or `dummy` for local) |
| `target_lang` | Output Language | `Chinese`, `English`, `Japanese` |

The Translation tab lists Alibaba Cloud Qwen-MT first, followed by DeepSeek Official,
SiliconFlow, and custom OpenAI-compatible endpoints. Qwen-MT models use
their required single-user-message format and `translation_options` automatically.
API keys stay in the ignored local `config.ini`; model names remain editable and
can also be fetched from `/models`.

Use **Course Domain** to provide subject context. It is sent as Qwen-MT's `domains`
option and is included in the system prompt for generic LLM providers, helping keep
computer science and mathematics terminology accurate and consistent.

Set `fast_backend = apple` under `[translation]` to display an on-device draft
before the configured LLM returns its refined translation. Apple Translation
requires its source/target language assets to be installed on macOS.

Live partial hypotheses use Apple Translation only. The remote LLM is called
only for finalized utterances, so a slow or blocked API cannot delay the local
draft. Stage timings and failures are written to `logs/runtime.log`; open it
from the Dashboard with **Open Runtime Log**.

The Apple draft is display-only: finalized remote requests translate the English
source directly and stream their result over the draft. SiliconFlow
`deepseek-ai/DeepSeek-V4-Flash` automatically sends `enable_thinking = false`;
generic translation requests use `temperature = 0` and a 256-token output cap.
Remote AI refinement has a three-second end-to-end deadline with retries disabled.
Two requests may run concurrently and only the newest third request may wait;
newer finalized speech replaces an older pending request. Generic models receive
one previous finalized English segment as context, while Qwen-MT remains a
single-turn translation request without context.

Choose `glass` or `notch` under **Subtitle Mode** on the Dashboard. On MacBooks
with a camera housing, `notch` uses the native SwiftUI/AppKit
[DynamicNotchKit](https://github.com/MrKai77/DynamicNotchKit) component instead
of the Qt overlay. New subtitles expand from the physical notch and compact after
six seconds of inactivity. **Glass** switches to the resizable overlay. Drag any
edge or corner to resize; its last position and size are restored on the next
launch. **Exit** stops the translator. The native helper builds during
`install_mac.sh`.

#### `[transcription]` Section
| Parameter | Description | Details |
| :--- | :--- | :--- |
| `backend` | ASR Engine | `apple` (macOS 26 native), `whisper`, `mlx`, `funasr` |
| `whisper_model` | Whisper Model Size | `tiny` (fast), `large-v3` (accurate) |
| `funasr_model` | FunASR Model Name | `paraformer-zh` (Chinese), `SenseVoiceSmall` (Multi-lang) |
| `device` | Compute Unit | `auto` (Apple Neural Engine), `cuda` (NVIDIA) |

For the lowest-latency microphone transcription on macOS 26+, set `backend = apple`.
The native helper uses Apple's on-device `SpeechAnalyzer`/`SpeechTranscriber`, emits
volatile and finalized results continuously, and builds automatically with the installed
Xcode Command Line Tools. Run `./build_apple_speech.sh` manually to rebuild it.

`./start_mac.sh` starts the Dashboard directly for fast, stable classroom use.
Developers can opt into source-file hot reload with
`REALTIME_TON_DEV_RELOAD=1 ./start_mac.sh`.

#### `[audio]` Section
| Parameter | Description | Details |
| :--- | :--- | :--- |
| `silence_threshold`| Sensitivity | `0.005` (Quiet) to `0.05` (Loud) |
| `device_index` | Audio source | `system` for macOS app/video audio, `auto`, or mic index `0`, `1`... |
| `update_interval` | Partial subtitle refresh | `0.5` seconds recommended for classroom use |

Select **System Audio (ScreenCaptureKit — videos/apps)** in the Dashboard to
translate audio played by browsers and media apps without BlackHole. The first
launch requires **System Settings → Privacy & Security → Screen & System Audio
Recording** permission; restart the translator after granting it. This source
excludes the translator process itself to avoid feedback loops.

## Troubleshooting
- **No Audio?** Check the terminal for capture logs. For System Audio, grant
  Screen & System Audio Recording and restart; for a microphone, grant Microphone
  access. BlackHole remains optional for custom audio routing.
- **Resize not working?** Use the designated "◢" handle in the bottom-right.
- **Hot Reload**: Modify any `.py` file or save settings in the UI to trigger a reload.

## 🎯 Using FunASR (NEW!)

FunASR is Alibaba's industrial-grade ASR toolkit with excellent Chinese language support.

**Quick Start:**
1. Set backend to `funasr` in Settings or `config.ini`
2. Choose a FunASR model (e.g., `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` for Chinese)
3. Models auto-download on first use from ModelScope

**Recommended Models:**
- **Chinese (Offline)**: `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`
- **Chinese (Streaming)**: `iic/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online`
- **English (Streaming)**: `iic/speech_UniASR_asr_2pass-en-16k-common-vocab1080-tensorflow1-online`
- **Multi-language**: `iic/SenseVoiceSmall` or `FunAudioLLM/SenseVoiceSmall`
- **Latest 31-language model**: `FunAudioLLM/Fun-ASR-Nano-2512` (Supports dialects, accents, lyrics)

**Note**: FunASR model names must include the namespace (e.g., `iic/` or `FunAudioLLM/`)


## License: MIT
Copyright 2025 Van

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
