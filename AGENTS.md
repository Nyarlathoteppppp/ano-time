# Anotime agent guide

Read [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md) before changing runtime
code. It is the maintained handoff record for the live translation pipeline.

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

## Repository conventions

- `main.py` owns Pipeline lifecycle and publishes subtitle events.
- `translation_preview/` owns bounded remote preview scheduling.
- `translation_context.py` is pure policy code; it must not import Qt, network,
  config, or providers.
- `docs/AGENT_HANDOFF.md` must be updated when stage ordering, context policy,
  provider routing, or the release check changes.
