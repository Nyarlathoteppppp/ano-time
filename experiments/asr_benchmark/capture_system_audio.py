#!/usr/bin/env python3
"""Capture a fixed 16 kHz mono system-audio sample for fair ASR replay."""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from system_audio_capture import SystemAudioCapture


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=90.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    capture = SystemAudioCapture(sample_rate=16_000, streaming_step_size=0.05)
    deadline = time.monotonic() + args.seconds
    chunks: list[np.ndarray] = []
    try:
        for chunk in capture.generator():
            chunks.append(np.asarray(chunk, dtype=np.float32).copy())
            if time.monotonic() >= deadline:
                break
    finally:
        capture.stop()

    audio = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * np.iinfo(np.int16).max).astype("<i2")
    with wave.open(str(args.output), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(pcm.tobytes())
    print(f"captured {len(audio) / 16_000:.1f}s -> {args.output}")


if __name__ == "__main__":
    main()
