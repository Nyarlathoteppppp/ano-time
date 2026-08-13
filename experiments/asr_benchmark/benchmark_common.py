"""Shared, dependency-light measurement helpers for local ASR experiments."""

from __future__ import annotations

import json
import subprocess
import threading
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


@dataclass
class ResourceSample:
    elapsed_ms: int
    cpu_percent: float
    rss_mb: float


class ProcessSampler:
    """Samples only the tested child process; never the whole desktop."""

    def __init__(self, pid: int, interval_seconds: float = 0.25):
        self.pid = pid
        self.interval_seconds = interval_seconds
        self._started_at = 0.0
        self._samples: list[ResourceSample] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._started_at = time.monotonic()
        self._thread.start()

    def stop(self) -> list[dict[str, float | int]]:
        self._stop.set()
        self._thread.join(timeout=1)
        return [asdict(sample) for sample in self._samples]

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                output = subprocess.check_output(
                    ["ps", "-o", "%cpu=", "-o", "rss=", "-p", str(self.pid)],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip().split()
                if len(output) != 2:
                    continue
                self._samples.append(ResourceSample(
                    elapsed_ms=int((time.monotonic() - self._started_at) * 1000),
                    cpu_percent=float(output[0]),
                    rss_mb=round(int(output[1]) / 1024, 1),
                ))
            except (subprocess.CalledProcessError, ValueError):
                return


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("benchmark input must be 16-bit mono WAV")
        sample_rate = source.getframerate()
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
    return audio.astype(np.float32) / 32768.0, sample_rate


def first_audio_onset_ms(audio: np.ndarray, sample_rate: int, threshold: float = 0.003) -> int:
    """Approximate onset using the same 50 ms window used by the capture path."""
    window = max(1, sample_rate // 20)
    for index in range(0, len(audio), window):
        block = audio[index:index + window]
        if block.size and float(np.sqrt(np.mean(np.square(block)))) >= threshold:
            return int(index * 1000 / sample_rate)
    return 0


def write_result(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize_resources(samples: list[dict[str, float | int]]) -> dict[str, float]:
    if not samples:
        return {"avg_cpu_percent": 0.0, "peak_cpu_percent": 0.0, "peak_rss_mb": 0.0}
    return {
        "avg_cpu_percent": round(sum(float(row["cpu_percent"]) for row in samples) / len(samples), 1),
        "peak_cpu_percent": round(max(float(row["cpu_percent"]) for row in samples), 1),
        "peak_rss_mb": round(max(float(row["rss_mb"]) for row in samples), 1),
    }
