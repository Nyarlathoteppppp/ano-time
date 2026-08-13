#!/usr/bin/env python3
"""Replay a WAV through AnoTime's formal Parakeet EOU helper.

The benchmark intentionally uses the same helper that ``parakeet_transcriber``
uses at runtime.  Keeping one Swift entry point prevents experiment-only
behavior from being mistaken for application behavior.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audio, sample_rate = load_wav(args.input)
    if sample_rate != 16_000:
        raise SystemExit("Parakeet EOU replay expects 16 kHz input")
    package_path = PROJECT_ROOT / "native" / "parakeet_eou"
    binary = package_path / ".build/release/ParakeetEOUHelper"
    if not binary.exists():
        raise SystemExit(
            "build Parakeet helper first: cd native/parakeet_eou && swift build -c release"
        )

    process = subprocess.Popen(
        [str(binary)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    events: list[dict] = []
    events_lock = threading.Lock()
    ready = threading.Event()
    clock = {"started_at": None}
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        assert process.stdout
        for raw_line in iter(process.stdout.readline, b""):
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if event.get("type") == "status" and event.get("status") == "ready":
                ready.set()
                continue
            started_at = clock["started_at"]
            if started_at is None:
                continue
            event["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
            if event.get("type") in {"result", "error"}:
                with events_lock:
                    events.append(event)

    def read_stderr() -> None:
        assert process.stderr
        for raw_line in iter(process.stderr.readline, b""):
            stderr_lines.append(raw_line.decode("utf-8", errors="replace"))

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    if not ready.wait(timeout=180):
        process.terminate()
        raise SystemExit("Parakeet EOU helper did not become ready")

    sampler = ProcessSampler(process.pid)
    sampler.start()
    started_at = time.monotonic()
    clock["started_at"] = started_at
    assert process.stdin
    frame_size = sample_rate // 20  # 50 ms, exactly AnoTime's live feed cadence.
    for offset in range(0, len(audio), frame_size):
        pcm = (audio[offset:offset + frame_size] * 32767.0).astype("<i2", copy=False)
        process.stdin.write(pcm.tobytes())
        target = started_at + min(offset + frame_size, len(audio)) / sample_rate
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
    process.stdin.close()
    try:
        return_code = process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.terminate()
        return_code = process.wait(timeout=5)
    samples = sampler.stop()
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    write_result(args.output, {
        "backend": "parakeet_eou_160ms",
        "input": str(args.input),
        "audio_duration_ms": int(len(audio) * 1000 / sample_rate),
        "audio_onset_ms": first_audio_onset_ms(audio, sample_rate),
        "run_duration_ms": int((time.monotonic() - started_at) * 1000),
        "return_code": return_code,
        "events": events,
        "resources": summarize_resources(samples),
        "resource_samples": samples,
        "stderr": "".join(stderr_lines)[-2000:],
    })
    print(f"Parakeet: {len(events)} events -> {args.output}")


if __name__ == "__main__":
    main()
