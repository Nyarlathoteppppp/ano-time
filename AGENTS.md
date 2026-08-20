# Anotime agent guide

## Takeover snapshot — 2026-08-21

- Repository: `/Users/ywbw/realtime-ton-pyside6`; active branch:
  `codex/pyside6-migration`.
- Latest committed checkpoint: `ed66411` (`feat: harden classroom subtitle runtime`).
  It contains the PySide6 migration, native-notch transport reliability,
  Parakeet controls/reliability work, visible glass resize grip, GitHub CI
  templates, and their documented tests.
- There is intentionally **uncommitted** glass-subtitle smoothing work. Do not
  reset, checkout, stash, or discard it during takeover. Its exact files are
  `overlay_window.py`, `tests/unit/subtitles/test_overlay_layout.py`,
  `AGENTS.md`, `docs/AGENT_HANDOFF.md`,
  `docs/development/CHANGELOG.md`,
  `docs/development/MAINTENANCE_PROTOCOL.md`,
  `docs/development/README.md`, and
  `docs/development/GLASS_SUBTITLE_SMOOTHING_PLAN.md`.
- This uncommitted batch passed targeted subtitle/notch tests (50/50), full
  tests (489/489), Python compilation, `git diff --check`, and release audit.
  It still requires a real macOS 60–120 second glass-mode acceptance test
  before it may be committed.
- `AnoTime-macOS` is out of scope. Maintain only this repository unless the
  user explicitly changes scope.

Read [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md) before changing runtime
code. It is the maintained handoff record for the live translation pipeline.
Then read the plan document matching the module being changed.

## Immediate next step

Fully restart the desktop app and test glass mode with continuous system audio:
long Chinese wrapping, partial revisions, finalization, new segments, manual
history scrolling, lower-right `◢` resize grip, glass → notch → glass, and
stop/return to Dashboard. The expected result is that history remains still
during most partial updates; small movement is allowed only when the growth
cushion is exhausted, a segment finalizes, or a new segment arrives. Record the
result before changing smoothing constants or layout structure.

## Non-negotiable rules

- Apple ASR and Apple Translation are the fastest path. Remote work must never
  block, delay, or replace a newer Apple draft with an older result.
- Treat subtitle stage ordering, request deadlines, `latest-wins`, and context
  snapshots as compatibility contracts. Do not replace them with broad queues
  or synchronous calls.
- Do not put API keys, account IDs, lecture text, or runtime logs in commits,
  tests, screenshots, or documentation. Keychain references are intentional.
- Keep Smart Hybrid and Single Model separate. A usability change for Single
  Model must not silently alter the maintainer-only hybrid route.
- Run the full headless suite before committing. Changes to audio, Apple
  translation, subtitle presentation, helpers, or lifecycle code also need a
  real system-audio smoke test.
- Do not commit or push the current smoothing batch until the user has accepted
  the real-device result. Do not push any branch without explicit approval.
- Never use `git reset --hard` or `git checkout --` in this repository. Treat
  a dirty tree as user-owned unless the current task created the exact change.

## Repository conventions

- `main.py` owns Pipeline lifecycle and publishes subtitle events.
- `translation_preview/` owns bounded remote preview scheduling.
- `translation_context.py` is pure policy code; it must not import Qt, network,
  config, or providers.
- `docs/AGENT_HANDOFF.md` must be updated when stage ordering, context policy,
  provider routing, or the release check changes.
- The glass renderer is one chronological scroll projection. The earlier fixed
  "current cue + isolated history" layout failed real use and was reverted;
  read `docs/development/GLASS_SUBTITLE_SMOOTHING_PLAN.md` before changing
  `overlay_window.py`.
- Use `.venv-pyside`, not system Python. Required checks are
  `./tools/run_tests.sh`, `git diff --check`, and
  `./.venv-pyside/bin/python tools/release_audit.py .`.
