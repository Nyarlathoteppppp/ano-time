#!/usr/bin/env python3
"""Summarize Anotime latency stages from the asynchronous runtime log."""

import argparse
import json
import math
import os
from statistics import median


STAGES = (
    ("ASR first partial", "asr_first_partial", "elapsed_ms"),
    ("Apple partial", "apple_partial", "elapsed_ms"),
    ("Apple final", "apple_final", "elapsed_ms"),
    ("Groq bridge", "groq_bridge", "elapsed_ms"),
    ("AI final", "llm_refine", "elapsed_ms"),
    ("Exit", "session_stop", "elapsed_ms"),
    ("Pause", "session_pause", "elapsed_ms"),
    ("Resume", "session_resume", "elapsed_ms"),
)


def parse_record(line):
    fields = {}
    for part in line.split("|")[1:]:
        part = part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def percentile(values, percentile_value):
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return ordered[rank]


def collect(log_path, last_lines=None):
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    if last_lines:
        lines = lines[-last_lines:]
    samples = {stage: [] for _, stage, _ in STAGES}
    for line in lines:
        record = parse_record(line)
        stage = record.get("stage")
        if stage not in samples or record.get("status", "ok") not in (
            "ok", "shown"
        ):
            continue
        metric = next(metric for _, name, metric in STAGES if name == stage)
        try:
            samples[stage].append(float(record[metric]))
        except (KeyError, ValueError):
            continue
    return samples


def summarize(samples):
    result = {}
    for label, stage, _ in STAGES:
        values = samples[stage]
        result[label] = {
            "count": len(values),
            "p50_ms": median(values) if values else None,
            "p95_ms": percentile(values, 0.95),
            "min_ms": min(values) if values else None,
            "max_ms": max(values) if values else None,
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="logs/runtime.log")
    parser.add_argument("--last-lines", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not os.path.exists(args.log):
        parser.error(f"runtime log not found: {args.log}")

    result = summarize(collect(args.log, args.last_lines))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print("Stage                 count    p50 ms    p95 ms     min ms     max ms")
    print("-" * 72)
    for label, metrics in result.items():
        if not metrics["count"]:
            print(f"{label:<21}{0:>5}      n/a       n/a        n/a        n/a")
            continue
        print(
            f"{label:<21}{metrics['count']:>5}"
            f"{metrics['p50_ms']:>10.0f}{metrics['p95_ms']:>10.0f}"
            f"{metrics['min_ms']:>11.0f}{metrics['max_ms']:>11.0f}"
        )


if __name__ == "__main__":
    main()
