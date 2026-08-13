#!/usr/bin/env python3
"""Replay a saved WAV through AnoTime's existing Apple Speech helper."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apple_transcriber import AppleSpeechTranscriber
from benchmark_common import (
    ProcessSampler,
    first_audio_onset_ms,
    load_wav,
    summarize_resources,
    write_result,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audio, sample_rate = load_wav(args.input)
    if sample_rate != 16_000:
        raise SystemExit("Apple replay expects 16 kHz input")

    events: list[dict] = []
    events_lock = threading.Lock()
    started_at = 0.0

    def on_result(text: str, final: bool) -> None:
        if not text.strip():
            return
        with events_lock:
            events.append({
                "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                "text": text,
                "final": final,
            })

    transcriber = AppleSpeechTranscriber(
        language="en", sample_rate=sample_rate, on_result=on_result,
    )
    transcriber.start()
    if not transcriber.process:
        raise SystemExit("Apple Speech helper did not start")
    sampler = ProcessSampler(transcriber.process.pid)
    sampler.start()

    started_at = time.monotonic()
    frame_size = sample_rate // 20  # 50 ms — mirrors AnoTime Apple input cadence.
    for offset in range(0, len(audio), frame_size):
        transcriber.feed(audio[offset:offset + frame_size])
        target = started_at + min(offset + frame_size, len(audio)) / sample_rate
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
    transcriber.stop()
    samples = sampler.stop()
    duration_ms = int((time.monotonic() - started_at) * 1000)
    write_result(args.output, {
        "backend": "apple_speech",
        "input": str(args.input),
        "audio_duration_ms": int(len(audio) * 1000 / sample_rate),
        "audio_onset_ms": first_audio_onset_ms(audio, sample_rate),
        "run_duration_ms": duration_ms,
        "events": events,
        "resources": summarize_resources(samples),
        "resource_samples": samples,
    })
    print(f"Apple: {len(events)} events -> {args.output}")


if __name__ == "__main__":
    main()
