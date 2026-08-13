#!/usr/bin/env python3
"""Rolling-window MLX Whisper baseline for the same WAV used by Apple/Parakeet."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmark_common import (
    ProcessSampler,
    first_audio_onset_ms,
    load_wav,
    summarize_resources,
    write_result,
)


def _transcribe(audio: np.ndarray, model: str) -> str:
    import mlx_whisper

    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=model,
        language="en",
        verbose=False,
        condition_on_previous_text=False,
        temperature=0.0,
    )
    return " ".join(str(result.get("text", "")).split())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--model", default="mlx-community/whisper-medium-mlx",
        help="MLX Whisper repository; project cache already has medium.",
    )
    parser.add_argument("--window-seconds", type=float, default=6.0)
    parser.add_argument("--step-seconds", type=float, default=0.8)
    parser.add_argument(
        "--no-prewarm", action="store_true",
        help="Include model-load latency instead of mirroring AnoTime startup warmup.",
    )
    args = parser.parse_args()
    audio, sample_rate = load_wav(args.input)
    if sample_rate != 16_000:
        raise SystemExit("MLX Whisper replay expects 16 kHz input")

    # Keep resource process attribution simple and reproducible: this worker is
    # the child process being measured rather than the desktop or the caller.
    worker_pid = os.getpid()
    sampler = ProcessSampler(worker_pid)
    sampler.start()
    events: list[dict] = []
    onset = first_audio_onset_ms(audio, sample_rate)
    window_samples = int(args.window_seconds * sample_rate)
    step_samples = int(args.step_seconds * sample_rate)
    started_at = time.monotonic()
    next_offset = max(step_samples, onset * sample_rate // 1000 + step_samples)
    previous_text = ""
    try:
        if not args.no_prewarm:
            # AnoTime calls Transcriber.warmup() before its audio loop. Keep the
            # first visible benchmark event comparable to normal app use.
            _transcribe(np.zeros(sample_rate, dtype=np.float32), args.model)
        started_at = time.monotonic()
        while next_offset <= len(audio):
            target = started_at + next_offset / sample_rate
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            window_start = max(0, next_offset - window_samples)
            text = _transcribe(audio[window_start:next_offset], args.model)
            if text and text != previous_text:
                events.append({
                    "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                    "audio_offset_ms": int(next_offset * 1000 / sample_rate),
                    "text": text,
                    "final": False,
                })
                previous_text = text
            next_offset += step_samples
        final_text = _transcribe(audio, args.model)
        events.append({
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            "audio_offset_ms": int(len(audio) * 1000 / sample_rate),
            "text": final_text,
            "final": True,
        })
    finally:
        samples = sampler.stop()

    write_result(args.output, {
        "backend": "mlx_whisper_rolling",
        "model": args.model,
        "input": str(args.input),
        "audio_duration_ms": int(len(audio) * 1000 / sample_rate),
        "audio_onset_ms": onset,
        "rolling_window_seconds": args.window_seconds,
        "rolling_step_seconds": args.step_seconds,
        "prewarmed": not args.no_prewarm,
        "events": events,
        "resources": summarize_resources(samples),
        "resource_samples": samples,
        "notes": "Rolling re-transcription baseline, not a native token-streaming Whisper engine.",
    })
    print(f"MLX Whisper: {len(events)} events -> {args.output}")


if __name__ == "__main__":
    main()
