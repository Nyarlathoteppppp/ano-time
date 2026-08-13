#!/usr/bin/env python3
"""Create a Markdown comparison table from normalized benchmark JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _meaningful(text: str) -> bool:
    return len(text.strip().split()) >= 3


def _metrics(payload: dict) -> dict[str, str]:
    events = payload.get("events", [])
    onset = int(payload.get("audio_onset_ms", 0))
    partials = [
        event for event in events
        if event.get("type", "result") in {"partial", "result"}
        and not event.get("final")
    ]
    meaningful = [event for event in partials if _meaningful(event.get("text", ""))]
    finals = [event for event in events if event.get("final") or event.get("type") in {"eou", "final"}]

    def delay(event: dict | None) -> str:
        if not event:
            return "—"
        return f"{max(0, int(event['elapsed_ms']) - onset)} ms"

    def after_audio(event: dict | None) -> str:
        if not event:
            return "—"
        duration = int(payload.get("audio_duration_ms", 0))
        return f"{max(0, int(event['elapsed_ms']) - duration)} ms"

    resource = payload.get("resources", {})
    return {
        "backend": payload.get("backend", "unknown"),
        "first": delay(partials[0] if partials else None),
        "stable": delay(meaningful[0] if meaningful else None),
        "final_after_audio": after_audio(finals[-1] if finals else None),
        "updates": str(len(partials)),
        "cpu": f"{resource.get('avg_cpu_percent', 0):.1f}% / peak {resource.get('peak_cpu_percent', 0):.1f}%",
        "memory": f"{resource.get('peak_rss_mb', 0):.0f} MB",
        "status": "OK" if payload.get("return_code", 0) == 0 and not any(e.get("type") == "error" for e in events) else "check result",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [_metrics(json.loads(path.read_text(encoding="utf-8"))) for path in args.results]
    lines = [
        "# Local ASR benchmark",
        "",
        "Same saved 16 kHz system-audio WAV replayed sequentially. Apple and Parakeet use true incremental native engines; MLX Whisper is a rolling re-transcription baseline.",
        "",
        "| Engine | First partial after audio onset | First ≥3-word phrase | Final after audio ends | Partial updates | CPU avg/peak | Peak RAM | Result |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['backend']} | {row['first']} | {row['stable']} | {row['final_after_audio']} | "
            f"{row['updates']} | {row['cpu']} | {row['memory']} | {row['status']} |"
        )
    lines += [
        "",
        "Notes:",
        "- CPU/RAM are for the ASR child process only; they exclude the capture process and UI.",
        "- No Chinese translation request is part of this benchmark. Apple translation latency is measured separately in the normal AnoTime diagnostic log.",
        "- Term accuracy requires a transcript ground truth; this run reports latency/resource behavior only.",
    ]
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
