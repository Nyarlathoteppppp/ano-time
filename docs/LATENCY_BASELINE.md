# Latency baseline

Snapshot generated from `logs/runtime.log` before structural refactoring.
Values are milliseconds.

| Stage | Samples | p50 | p95 | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| ASR first partial | 751 | 676 | 9,676 | 0 | 525,041 |
| Apple partial | 5,615 | 50 | 99 | 10 | 454 |
| Apple final | 847 | 44 | 96 | 0 | 290 |
| Groq bridge | 492 | 400 | 674 | 98 | 994 |
| AI final | 751 | 863 | 1,277 | 0 | 2,874 |
| Exit | 0 | — | — | — | — |
| Pause | 0 | — | — | — | — |
| Resume | 0 | — | — | — | — |

The ASR history spans multiple sessions and includes idle/sleep gaps, so its
p95 and maximum are not a clean current-session latency measurement. Use
`--last-lines N` immediately after a controlled lecture test for regression
comparison. Exit, pause and resume telemetry was added with this safety net;
their first baseline samples will be recorded after the updated app runs.

Regenerate the report with:

```bash
.venv/bin/python tools/latency_baseline.py
```
