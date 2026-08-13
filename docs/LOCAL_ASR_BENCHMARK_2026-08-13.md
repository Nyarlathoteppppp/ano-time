# Local ASR comparison — 2026-08-13

## Scope

This is a local, sequential replay benchmark on this Mac. It compares the
three ASR paths that can now be selected or evaluated by AnoTime:

- **Apple Speech** — existing AnoTime default native streaming path.
- **Parakeet EOU 120M** — FluidAudio CoreML 160 ms streaming chunks; optional,
  experimental, English-only path.
- **MLX Whisper medium** — existing `mlx` backend, evaluated as a 6-second
  rolling re-transcription baseline with 0.8-second updates.

The saved audio was captured once from ScreenCaptureKit, then each engine was
replayed **sequentially**. This prevents three ASR engines from competing for
CPU, GPU/Metal, Neural Engine, and audio capture resources at the same time.

The browser lecture segment was 89.65 seconds, 16 kHz mono English audio.

## Live latency and resource table

| Metric | Apple Speech | Parakeet EOU 160 ms | MLX Whisper medium (warm) |
|---|---:|---:|---:|
| Audio onset → first English token | 1.04 s | **0.82 s** | 1.71 s |
| Audio onset → first ≥3-word phrase | 1.93 s | **1.33 s** | 1.71 s |
| Audio end → English final / EOU | 0.24 s | **0.15 s** | 65.5 s |
| Partial updates | 405 | 347 | 111 |
| Full audio processing time | 90.0 s | **89.8 s** | 155.2 s |
| Real-time factor | **1.00×** | **1.00×** | 1.73× |
| ASR process CPU average / peak | **1.0% / 3.4%** | 28.1% / 58.8% | 23.9% / 106.4% |
| ASR process peak resident memory | **51 MB** | 296 MB | 1.92 GB |
| Current suitability for fast classroom subtitles | **Default: best efficiency and sentence-final behavior** | Fast experimental English alternative | Accuracy / offline fallback only |

`160 ms` is Parakeet's audio chunk size, **not** its audio-to-first-word latency.
With AnoTime's formal helper and 50 ms input cadence it beat Apple on first
partial and first phrase in this continuous-audio replay, and it completed in
real time. It costs materially more sustained CPU and memory. More importantly,
on the uninterrupted 89.65-second lecture it emitted one EOU/final only at the
end, while Apple formed 11 natural finals. That means Parakeet still needs
longer live-course validation before replacing Apple as the default.

MLX Whisper's first visible update was measured after its normal AnoTime-style
warm-up. A cold model load is slower. Its strong final text quality does not
make it a replacement for the low-latency Apple path.

## Controlled terminology sample

The following synthetic English sample was spoken by macOS locally, so its
expected terminology is known: `statistical machine learning`,
`regularization`, `bias variance`, `covariance matrix`, `likelihood`,
`gradient descent`, `AI planning`, `admissible heuristic`, `overestimates`,
`A* search`, `priority queue`, `closed set`.

| Engine | Recognized required terms | Observed error |
|---|---:|---|
| Apple Speech | 11 / 12 | `priority cue` instead of `priority queue` |
| Parakeet EOU | 9 / 12 | `overrestimates`, `A stars`, `priority q` |
| MLX Whisper medium | **12 / 12** | No term miss in this clean sample |

This is a controlled vocabulary check, not a claim of professor-accent WER.
Actual course accuracy must continue to be judged against manually reviewed
lecture segments. AnoTime's course-profile glossary and finalized-ASR
corrections remain downstream safeguards for all engines.

## Metrics not attributed to an ASR engine

The capture had no timestamped human transcript, so **first correct word** and
true word-error rate cannot be measured honestly from it. The “first ≥3-word
phrase” row is a repeatable usability proxy, not a correctness claim.

Chinese draft latency, remote-final latency, and Chinese rewrite frequency are
also deliberately excluded from the table. All three ASRs enter the same
AnoTime downstream path: Apple draft → optional bridge/Preview → remote Final.
The number of ASR partial updates above is the relevant input-side churn
indicator: Apple 405, Parakeet 347, MLX 111 on this clip. A full end-to-end
test must use Diagnostics and a manually timed transcript.

No whole-device energy measurement was taken. CPU/RAM numbers cover only the
helper/worker process, not ScreenCaptureKit, Qt, or Apple system speech
services, so they are a resource signal rather than an exact battery or heat
ranking.

## Product decision

1. Keep **Apple Speech** as the default: it remains markedly cheaper and its
   sentence-final behavior is more mature.
2. Keep **Parakeet EOU** as an explicit experimental English choice for users
   who prioritize the earliest visible English partial and accept higher CPU.
3. Keep **MLX Whisper** available for users who accept higher latency for better
   long-form final English text.
4. Never auto-select Parakeet or make it a fallback from Apple yet.
5. Do not change Apple Translation, remote Preview, Final, or subtitle
   scheduling because of this experiment.

## Reproduce

```bash
cd /Users/ywbw/realtime-ton-pyside6

# capture a new same-source sample (requires Terminal/Python ScreenCaptureKit permission)
./.venv-pyside/bin/python experiments/asr_benchmark/capture_system_audio.py \
  --seconds 90 --output experiments/asr_benchmark/captures/sample.wav

# run all three sequentially
./.venv-pyside/bin/python experiments/asr_benchmark/run_apple_replay.py \
  experiments/asr_benchmark/captures/sample.wav \
  --output experiments/asr_benchmark/results/apple.json
./.venv-pyside/bin/python experiments/asr_benchmark/run_parakeet_replay.py \
  experiments/asr_benchmark/captures/sample.wav \
  --output experiments/asr_benchmark/results/parakeet.json
./.venv-pyside/bin/python experiments/asr_benchmark/run_mlx_whisper_replay.py \
  experiments/asr_benchmark/captures/sample.wav \
  --output experiments/asr_benchmark/results/mlx.json
./.venv-pyside/bin/python experiments/asr_benchmark/make_report.py \
  experiments/asr_benchmark/results/apple.json \
  experiments/asr_benchmark/results/parakeet.json \
  experiments/asr_benchmark/results/mlx.json \
  --output experiments/asr_benchmark/results/LOCAL_ASR_COMPARISON.md
```

Generated audio and result JSON files remain ignored by Git. The benchmark
code and this measured report are kept in the repository for future agents.
