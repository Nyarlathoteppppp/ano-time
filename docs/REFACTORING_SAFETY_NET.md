# Refactoring safety net

Ano Time treats latency and visible subtitle behavior as compatibility
requirements. Refactoring is accepted only when the automated contracts pass
and a real microphone/system-audio smoke test shows no latency regression.

## Automated coverage

| Area | Contract |
| --- | --- |
| Pipeline lifecycle | Dedicated daemon start; stop releases audio, worker thread and Apple translator |
| Subtitle stages | partial → Apple final → Groq bridge → AI final is monotonic; late drafts cannot overwrite later stages |
| Realtime queues | Groq and final AI queues retain active work and only the newest pending sentence |
| Deadlines | Expired AI work never calls a provider or updates visible subtitles |
| Glass layout | Every wrapped English/Chinese label receives its full calculated height |
| Native notch | Latest-frame pipe, long-text display splitting, finalized history, pause/resume/exit protocol |
| Configuration | System-audio aliases, three-second deadline, relative terminology paths and Keychain references |
| Credentials | Atomic plaintext migration, failed-migration preservation and masked references |
| Provider quotas | RPM, TPM, daily requests, Cloudflare neurons, cooldown recovery and automatic fallback |
| System audio | Helper build, launch error details, permission stderr and clean stop protocol |
| Runtime logging | Full telemetry queue never blocks the caller |

Run all contracts:

```bash
./tools/run_tests.sh
```

## Latency baseline

The runtime log records these user-visible boundaries:

- `asr_first_partial`
- `apple_partial`
- `apple_final`
- `groq_bridge`
- `llm_refine`
- `session_stop`
- `session_pause`
- `session_resume`

Summarize the current log:

```bash
.venv/bin/python tools/latency_baseline.py
```

The initial pre-refactor snapshot is stored in
[`LATENCY_BASELINE.md`](LATENCY_BASELINE.md).

Use `--last-lines N` to isolate a recent test session or `--json` for machine
comparison. Compare p50 and p95 before and after each refactor. A structural
change must not increase the latency-critical Apple path or allow remote work
to delay subsequent speech.

## Runtime log lifecycle

The confirmed primary app process creates a fresh `logs/runtime.log` on every
launch. The previous session is moved to `logs/history/`; at most five sessions
and seven days are retained. Reopening the desktop launcher while Ano Time is
already running does not rotate or interrupt the active log.

While a Pipeline is active, `runtime_performance` records process CPU, peak
resident memory, thread count and subtitle event rate every two seconds. The
sampler uses process counters only; it does not execute `ps`, inspect other
applications or run on the latency-critical audio callback.

## Manual release gate

After automated tests, verify on a real Mac:

1. Microphone recognition and Apple partial subtitles.
2. ScreenCaptureKit browser-video capture.
3. `Control + S` launch, pause and resume.
4. Physical notch and glass modes.
5. Long Chinese text, resizing and fullscreen overlay.
6. Exit returns to the control center and releases capture.
7. Provider timeout/fallback and Keychain persistence.
