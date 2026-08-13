# Local ASR benchmark

This directory is intentionally independent from AnoTime's production pipeline.
It answers one question before a backend is exposed in the control center:

> On this Mac, does Parakeet EOU or MLX Whisper actually beat Apple Speech for live English subtitle latency and resource use?

## Method

1. Capture a fixed 16 kHz mono WAV from ScreenCaptureKit.
2. Replay it **sequentially** through Apple Speech, Parakeet EOU, and MLX Whisper.
3. Emit JSON measurements and generate a Markdown table.

Sequential replay prevents competing ASR engines from distorting each other's
CPU, GPU, Neural Engine, or audio-capture behavior.

## Backends

- `apple_speech`: existing AnoTime native Apple streaming path.
- `parakeet_eou_160ms`: FluidAudio CoreML Parakeet EOU 120M, a true incremental
  model with 160 ms chunks. First use downloads its CoreML model into
  `~/Library/Application Support/FluidAudio`.
- `mlx_whisper_rolling`: MLX Whisper with a 6 s rolling window and 0.8 s update
  cadence. This is a fair practical baseline, but not token-native streaming.

Captured WAVs and generated results are ignored by Git.
