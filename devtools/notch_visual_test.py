#!/usr/bin/env python3
"""Deterministic native-notch visual test; no microphone or API calls."""

import json
import os
import signal
import subprocess
import threading
import time


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = os.path.join(
    ROOT, "native_notch", ".build", "release", "RealtimeNotchHelper"
)

SAMPLES = [
    (
        "A heuristic estimates the remaining cost from the current state.",
        "启发式函数估计从当前状态到目标的剩余代价。",
    ),
    (
        "An admissible heuristic never overestimates the true optimal cost.",
        "可采纳启发式函数不会高估真实的最优代价。",
    ),
    (
        "The covariance matrix describes how random variables vary together.",
        "协方差矩阵描述多个随机变量如何共同变化。",
    ),
    (
        "Regularisation controls variance by penalising excessive complexity.",
        "正则化通过惩罚过高的模型复杂度来控制方差。",
    ),
]


def fragment(segment_id, original, translated, finalized, committed):
    return {
        "id": segment_id * 1000,
        "original": original,
        "translated": translated,
        "finalized": finalized,
        "committedPrefixLength": committed,
    }


def cue(segment_id, original, translated, finalized=False, committed=0):
    return {
        "id": segment_id,
        "segmentID": segment_id,
        "original": original,
        "translated": translated,
        "finalized": finalized,
        "committedPrefixLength": committed,
        "fragments": [
            fragment(
                segment_id, original, translated, finalized, committed
            )
        ],
    }


def main():
    subprocess.run(
        [os.path.join(ROOT, "build_native_notch.sh")],
        check=True,
        cwd=ROOT,
    )
    process = subprocess.Popen(
        [BINARY],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    helper_closed = threading.Event()

    def drain(stream):
        for line in stream:
            text = line.rstrip()
            print(text, flush=True)
            try:
                event = json.loads(text).get("event")
            except (json.JSONDecodeError, AttributeError):
                event = None
            if event in {"exit", "glass"}:
                helper_closed.set()

    threading.Thread(target=drain, args=(process.stdout,), daemon=True).start()
    threading.Thread(target=drain, args=(process.stderr,), daemon=True).start()

    def stop(*_args):
        if process.poll() is None:
            try:
                process.stdin.write(json.dumps({"command": "quit"}) + "\n")
                process.stdin.flush()
                process.wait(timeout=2)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                process.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    history = []
    segment_id = 1
    print("Notch visual test running. Click the notch to select large mode.")
    while process.poll() is None and not helper_closed.is_set():
        original, final_translation = SAMPLES[(segment_id - 1) % len(SAMPLES)]
        words = original.split()
        partial_original = " ".join(words[:5])
        stages = (
            cue(segment_id, partial_original, "", False, 0),
            cue(
                segment_id,
                original,
                final_translation[: max(4, len(final_translation) // 2)],
                False,
                0,
            ),
            cue(
                segment_id,
                original,
                final_translation.replace("。", "……"),
                False,
                max(0, len(final_translation) // 3),
            ),
            cue(
                segment_id,
                original,
                final_translation,
                True,
                len(final_translation),
            ),
        )
        for index, active in enumerate(stages):
            if process.poll() is not None or helper_closed.is_set():
                break
            frame = history[-2:] + [active]
            try:
                process.stdin.write(json.dumps({
                    "items": frame,
                    "busyStages": [] if index == 3 else ["Draft"],
                }, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except BrokenPipeError:
                helper_closed.set()
                break
            time.sleep(0.75 if index < 3 else 1.15)
        history.append(stages[-1])
        segment_id += 1

    if process.poll() is None:
        process.wait(timeout=2)


if __name__ == "__main__":
    main()
