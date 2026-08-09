# Realtime Ton

**Native, low-latency English → Chinese live subtitles for macOS lectures, meetings, and fullscreen video.**

Realtime Ton combines Apple on-device speech recognition and translation with optional AI refinement. Provisional subtitles remain instant, stable sentences receive terminology-aware refinement, and every remote request is deadline-limited so a slow model can never block the live path.

It can listen directly to Mac system audio through ScreenCaptureKit—no BlackHole setup required—and render subtitles either as a resizable glass overlay or as an adaptive window attached to the physical MacBook notch.

> Built primarily for Apple Silicon MacBooks. The generic Python/Qt path can run on other platforms, but Apple Speech, Apple Translation, ScreenCaptureKit system audio, and the physical-notch UI are macOS-only.

## Screenshots

### Control center

![Realtime Ton glass control center](./demo/control-center.png)

### Physical notch and glass overlay

<p align="center">
  <img src="./demo/physical-notch.png" width="49%" alt="Realtime Ton subtitles expanding from the physical MacBook notch">
  <img src="./demo/glass-overlay.png" width="38%" alt="Realtime Ton resizable glass subtitle overlay">
</p>

## Why Realtime Ton

- **Live Apple Speech transcription** with visibly distinct provisional and finalized English.
- **Direct system-audio capture** through ScreenCaptureKit for browser videos, lectures, Zoom, and media apps—BlackHole is optional.
- **Speed-first translation pipeline**: Apple drafts appear immediately while remote AI refinement runs under a strict deadline.
- **Physical MacBook notch subtitles** with 1/2/3-message modes, centered adaptive width, long-translation segmentation, pause/resume, glass-mode switch, and exit controls.
- **Resizable glass overlay** that stays above fullscreen video and supports edge/corner resizing.
- **Optional terminology profiles** through editable TSV glossaries and finalized-ASR correction files; no maintainer-specific course vocabulary is enabled for new users.
- **OpenAI-compatible providers**, including Qwen-MT, DeepSeek, SiliconFlow, Groq, Gemini, Cloudflare Workers AI, and custom endpoints.
- **Quota-aware free-provider pool** with minute/day/token accounting, automatic fallback, cooldown recovery, and Qwen-MT fallback.
- **Latest-wins refinement queue**: stale work is dropped so subtitles cannot accumulate seconds behind the speaker.
- **Runtime latency log** for audio, ASR, local draft, bridge model, and final refinement stages.
- **Native `Control + S` global shortcut** backed by a resident macOS agent: launch the notch, pause, and resume without Accessibility or Input Monitoring permission.

### Free model options

- **Apple Speech + Apple Translation** — on-device and included with macOS.
- **GPT-OSS 20B** — GroqCloud free API tier: [Groq Console](https://console.groq.com/).
- **Gemini 3.5 Flash-Lite** — free tier: [Google AI Studio](https://aistudio.google.com/).
- **GLM-4.7-Flash** — Workers AI daily free allocation: [Cloudflare Dashboard](https://dash.cloudflare.com/).
- **Qwen-MT Flash** — Model Studio trial/new-user quota and fallback: [Alibaba Cloud Model Studio](https://bailian.console.aliyun.com/).

Free quotas and model availability can change; check each provider's console before relying on them for a full class.

## Requirements

Recommended configuration:

- Apple Silicon Mac
- macOS 26+ for native Apple `SpeechAnalyzer` / `SpeechTranscriber`
- Python 3.10+
- Xcode Command Line Tools
- Homebrew and FFmpeg

Whisper/MLX can be used when Apple Speech is unavailable. Windows has legacy launch scripts, but the current low-latency native feature set is macOS-focused.

## Install

```bash
git clone https://github.com/Nyarlathoteppppp/realtime-ton.git
cd realtime-ton
chmod +x install_mac.sh start_mac.sh
./install_mac.sh
```

If FFmpeg is missing:

```bash
brew install ffmpeg
```

The installer creates a project-local `.venv`, installs Python dependencies, builds the Apple Speech and native-notch helpers, and prepares `config.ini` from the example configuration.

### Optional desktop launcher

```bash
chmod +x install_desktop_app.sh install_hotkey_agent.sh
./install_desktop_app.sh
./install_hotkey_agent.sh
```

This installs **Realtime Translator.app** so the control center can be opened like a normal Mac application. The app is single-instance: opening it again activates the existing control center instead of creating duplicate translator windows.

The second command installs a per-user LaunchAgent named
`com.nyarlathotep.realtime-ton.hotkey`. It owns the native `Control + S`
shortcut independently of the control-center process, so the shortcut can
reopen the app after the Dashboard has been closed.

`Control + S` launches Physical MacBook Notch mode when stopped, pauses a
running session, and resumes a paused session. It uses Carbon
`RegisterEventHotKey`, so it does **not** require Accessibility or Input
Monitoring permission. macOS uses `Command + S` for Save, so the standard Save
command is unaffected.

The launcher fingerprints the checked-out source. After an update it closes the loaded Dashboard and starts the new code; otherwise it activates the existing instance. The control-center title shows the loaded Git revision.

The locally built launcher and native audio helper use local code signatures.
Run `install_desktop_app.sh` for first installation or when the launcher itself
changes—not for ordinary Python source updates. Rebuilding an app changes its
local signature and macOS may request privacy permission again.

## Quick start

```bash
./start_mac.sh
```

In the control center:

1. **Audio** → select `System Audio` for videos/apps or a microphone for an in-person class.
2. **Transcription** → select `Apple` for the lowest native latency, or `MLX` as the Apple Silicon Whisper path.
3. **Translation** → choose a provider/model and enter its API key.
4. **Subtitle Mode** → choose `Physical MacBook Notch` or `Glass`.
5. Click **Launch Translator**.

On macOS, API credentials are stored in the user Keychain. The ignored local
`config.ini` contains only `keychain://...` references; existing plaintext keys
are migrated automatically after a successful Keychain write. Never paste real
keys into issues, logs, screenshots, or README files. Rotate any key that has
been exposed publicly.

## macOS permissions

### Translate browser or application audio

Open:

**System Settings → Privacy & Security → Screen & System Audio Recording**

Enable **Realtime Translator**, then fully quit and reopen the application. Use **Audio → Test Permission & Audio** while a video is playing to distinguish a permission problem from valid but silent capture.

Depending on the macOS version and launch path, the permission list may show:

- **Realtime Translator** — desktop launcher/responsible application.
- **Realtime Translator Audio** — native ScreenCaptureKit helper.
- **Python** — local Dashboard process.

Enable every project entry that appears under **Screen & System Audio
Recording**. Some macOS versions also show a separate **System Audio Recording
Only** section; enable the Realtime Translator entry there as well. The generic
`applet` row is a legacy launcher identity and is not required.

After changing a permission, restart the running Dashboard. Changing a switch
does not update an already-running ScreenCaptureKit process.

### Translate microphone audio

Open:

**System Settings → Privacy & Security → Microphone**

Enable **Realtime Translator**, then restart it.

BlackHole is not required for the normal ScreenCaptureKit system-audio path. It remains available for custom routing on older or unusual setups.

### Global shortcut

No privacy permission is required. Install the resident agent once:

```bash
./install_hotkey_agent.sh
```

Verify it is running:

```bash
launchctl print "gui/$(id -u)/com.nyarlathotep.realtime-ton.hotkey"
tail -f /tmp/realtime-ton-hotkey.log
```

A successful startup includes:

```text
[Shortcut] Registered Control + S via Carbon
[Hotkey Agent] Ready
```

## Subtitle modes

### Physical MacBook notch

- Click the subtitle to cycle through 1, 2, and 3 visible messages.
- Right-click for **Pause/Resume**, **Glass Mode**, and **Exit**.
- Width grows immediately with longer text but shrinks with a short delay to prevent ASR-driven visual jitter.
- English and Chinese remain centered while the notch expands symmetrically.
- Long finalized translations are split only when they would exceed the available two-line display area.
- The notch compacts after six seconds without new speech.

### Glass overlay

- Drag the window to move it.
- Resize from any edge or corner.
- The last position and size are restored on the next launch.
- System-audio mode uses video-friendly transparency; microphone mode retains the regular glass surface.
- The native window level keeps subtitles visible above browser fullscreen video.

## Translation pipeline

```text
Audio
  → provisional Apple ASR
  → immediate Apple Translation draft
  → optional low-latency Groq bridge
  → finalized ASR segment
  → deadline-limited Gemini / Cloudflare / Qwen-MT refinement
```

Important real-time behavior:

- Every distinct Apple partial may update the local draft for minimum latency.
- Remote AI refinement runs on stable/finalized segments, not every growing ASR hypothesis.
- Punctuation-only finals are discarded; finals of three words or fewer keep the Apple draft but do not spend remote-model quota.
- Conservative finalized-text cleanup removes obvious streaming-ASR repetitions while preserving intentional emphasis.
- AI requests have a configurable hard deadline (`3.0s` by default) and no retry chain.
- Two refinements may run concurrently; only the newest pending request is retained.
- Late drafts cannot overwrite a higher-quality final result.
- Qwen-MT uses its native translation options without conversation context; generic models receive one previous finalized English segment for disambiguation.
- Translation prompts can identify a course domain and warn that ASR may contain recognition errors.

Stage timings and failures are written to `logs/runtime.log` and can be opened from the control center.

## Configuration

The dashboard writes ordinary settings and Keychain references to `config.ini`.
Secret values remain in macOS Keychain. A safe template is provided in
[`config.ini.example`](./config.ini.example).

### Recommended classroom profile

```ini
[translation]
target_lang = Chinese
domain = Postgraduate Computer Science–AI coursework. Preserve standard terminology in AI, machine learning, probability and statistics, linear algebra, optimization, and software engineering.
ai_deadline_seconds = 3.0
fast_backend = apple
# Leave these empty for general use. Enable only a glossary you selected.
glossary_path =
asr_corrections_path =

[transcription]
backend = apple
source_language = en

[audio]
device_index = system
silence_threshold = 0.005
update_interval = 0.5

[display]
mode = notch
```

### Main options

| Setting | Purpose |
| --- | --- |
| `translation.provider` | Translation provider or quota-aware provider pool |
| `translation.model` | Remote translation model |
| `translation.fast_backend` | Immediate local draft backend (`apple`) |
| `translation.ai_deadline_seconds` | Maximum useful lifetime of a remote refinement |
| `translation.glossary_path` | TSV terminology glossary |
| `translation.asr_corrections_path` | Optional finalized-English correction TSV |
| `transcription.backend` | `apple`, `mlx`, `whisper`, or `funasr` |
| `audio.device_index` | `system`, `auto`, or a microphone device index |
| `audio.silence_threshold` | Voice/silence sensitivity |
| `display.mode` | `notch` or `glass` |

## Optional terminology profiles

New installations do **not** load the maintainer's terminology files. For a general lecture, leave both settings empty:

```ini
glossary_path =
asr_corrections_path =
```

To opt in, create or select a TSV file and set its path explicitly. The bundled [`course_glossary.tsv`](./course_glossary.tsv) is an example profile for postgraduate Computer Science–AI coursework:

```tsv
heuristic function	启发式函数
admissible heuristic	可采纳启发式
state space	状态空间
```

Finalized-ASR corrections use the same two-column format:

```tsv
Ajail	Agile
code and fixed	code and fix
```

Enable the example files only when they match your course:

```ini
glossary_path = course_glossary.tsv
asr_corrections_path = asr_corrections.tsv
```

Corrections apply only after ASR finalization, never to the latency-critical provisional subtitle. Keep both files short and course-specific; only terms matched in the current sentence are sent to supported translation providers.

## Troubleshooting

### System audio stops with permission error

Confirm every visible project entry—**Realtime Translator**, **Realtime
Translator Audio**, and **Python**—is enabled under Screen & System Audio
Recording, then fully restart the Dashboard. If macOS still denies capture
after a local app rebuild, remove/reset only that project entry and grant the
current build again; the displayed switch may refer to an older local signature.

Do not repeatedly run `install_desktop_app.sh` while troubleshooting. It
rebuilds and re-signs the local launcher, which can invalidate the permission
you just granted.

### `Control + S` does nothing

Check the resident agent rather than Accessibility/Input Monitoring settings:

```bash
launchctl print "gui/$(id -u)/com.nyarlathotep.realtime-ton.hotkey"
tail -30 /tmp/realtime-ton-hotkey.log
```

If the agent is missing or stopped, reinstall it:

```bash
./install_hotkey_agent.sh
```

Each press should add `[Shortcut] Activated Control + S`. The agent is the only
hotkey owner; the Dashboard deliberately avoids a duplicate handler, preventing
a single press from pausing and immediately resuming.

### Speech works from a phone but not from a browser video

The microphone is active instead of ScreenCaptureKit. Select **System Audio**, run the audio test while the browser video is playing, and verify the home page reports `System Audio · ScreenCaptureKit active`.

### Subtitle does not stay above fullscreen video

Restart after updating. Both native notch and glass windows use macOS window levels and collection behavior intended for fullscreen Spaces.

### Translation returns `401 invalid_api_key`

The endpoint is reachable, but the configured key does not belong to that provider or host. Check Base URL, model name, and API key as one matching set.

### First launch is slow

MLX/Whisper models download on first use. Apple Speech may also need language assets. Later launches reuse local assets.

## Development

```bash
# Native helper builds
./build_apple_speech.sh
./build_native_notch.sh

# Tests
./.venv/bin/python -m unittest -q \
  test_groq_bridge.py \
  test_hybrid_translator.py \
  test_glossary.py \
  test_stable_prefix.py

# Optional source-file hot reload
REALTIME_TON_DEV_RELOAD=1 ./start_mac.sh
```

## Platform support

| Feature | macOS | Windows/Linux |
| --- | ---: | ---: |
| Microphone capture | Yes | Legacy/partial |
| Whisper/FunASR | Yes | Architecture supports it |
| Apple live ASR and translation | Yes | No |
| ScreenCaptureKit system audio | Yes | No |
| Physical MacBook notch UI | Yes | No |
| Generic OpenAI-compatible translation | Yes | Yes |
| Qt glass overlay | Yes | Legacy/partial |

## License

[MIT](./LICENSE) © Van and contributors.
