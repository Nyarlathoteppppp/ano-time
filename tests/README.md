# Test layout

The default suite is intentionally offline and fast:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -q
```

- `unit/`: one production module or one pure behavior per test file.
- `integration/`: contracts spanning the pipeline, dashboard, or native helpers.
- `performance/`: diagnostic and latency behavior; keep timing assertions tolerant.
- `fixtures/`: reusable test data and fakes only when at least two test modules need them.
- `support/`: small test utilities that do not duplicate production logic.

Rules:

1. Unit tests do not access the network, microphone, Keychain, or paid quotas.
2. Real-device and live-provider checks are not part of default discovery.
3. Prefer fake clocks to new sleeps; keep unavoidable thread timing tests isolated.
4. A regression gets the smallest test in the owning domain.
5. Split a file when it starts covering multiple production responsibilities.
