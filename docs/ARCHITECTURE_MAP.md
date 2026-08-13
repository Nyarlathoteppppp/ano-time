# AnoTime legacy prototype: architecture map

Last reviewed: 2026-08-14.

This document maps the local open-source classroom prototype in this repository. It is **not** the App Store product. The native App Store work is in the separate repository `AnoTime-macOS`; do not mix its Swift code, entitlements, build artifacts, or product decisions into this PySide6 runtime.

Read [AGENT_HANDOFF.md](AGENT_HANDOFF.md) before changing live code. That file defines compatibility contracts; this file explains where those contracts live.

## Product role and non-goals

The legacy application is a power-user reference implementation for macOS:

- captures microphone or ScreenCaptureKit system audio;
- produces English ASR, an Apple local Chinese draft, optional remote preview, and optional remote final refinement;
- presents captions in a Qt glass window or a separate native notch helper;
- records bilingual finalized lessons locally when enabled.

It is intentionally configuration-rich. It is not sandboxed, not signed as a single distributable App Store application, and may rely on Python helpers and user-provided API credentials. Do not market or package this repository as the App Store binary without a separate release project.

## Runtime diagram

```text
Dashboard / SessionController
  └─ captures SessionSettingsSnapshot at Launch
       └─ Pipeline (main.py)
            ├─ AudioCapture | SystemAudioCapture
            ├─ ASR adapter (Apple / Parakeet EOU / MLX / Whisper / FunASR)
            ├─ FastPath
            │    └─ Apple local Translation draft (must not await cloud work)
            ├─ optional bridge preview
            ├─ ProgressiveTranslationPreview
            ├─ final remote workflow
            └─ SegmentStore → SubtitleEvent stream
                   ├─ SubtitlePresentationCoordinator
                   ├─ display scheduler / fragment plan
                   ├─ Qt glass overlay OR native notch helper
                   └─ optional transcript / usage / diagnostics sinks
```

The only supported direction is left to right. Renderers, transcript sinks, and accounting code must never block audio, ASR, FastPath, or remote routing.

## Event and subtitle ownership

### Semantic state

| Module | Responsibility | Must not do |
| --- | --- | --- |
| `main.py` / `Pipeline` | lifecycle, ASR ingestion, event publication, pause/reset boundaries | perform UI layout decisions |
| `subtitle_event.py` | typed event stage/revision contract | know an ASR SDK or a provider |
| `segment_store.py` | canonical per-segment state and stale-result rejection | render or call the network |
| `subtitle_presentation_coordinator.py` | choose a pleasant visible revision from valid semantic revisions | discard transcript-worthy events |
| `subtitle_display_scheduler.py` | bounded frame pacing | change translation semantics |
| `display_fragment_plan.py` | display-only long-text splitting | change saved sentence boundaries |
| `subtitle_revision.py` | local diff/prefix revision planning | call an LLM |

`segment_id`, `revision`, and `SubtitleStage` are compatibility keys. A lower stage or an older revision must never reclaim a newer visible subtitle. Apple and remote translation can all update the same semantic segment, but each display event is judged by `SegmentStore` first.

### Stages

```text
ASR_PARTIAL → APPLE_PARTIAL → optional BRIDGE_PREVIEW
                           → AI_PREVIEW / AI_STREAM → AI_FINAL
ASR_FINAL   → APPLE_FINAL  ────────────────────────┘
```

Apple drafts are the immediate local fallback. A failed Preview is disposable; it must not cool down or poison final-provider routing. A failed or late final must leave the newest Apple draft visible. See the detailed current policies in `AGENT_HANDOFF.md`.

## ASR boundary

`transcriber.py` is the ASR facade used for non-Apple backends. Apple ASR has its own local helper path in `apple_transcriber.py` and `apple_speech_helper.swift`. System audio is owned by `system_audio_capture.py` and `apple_system_audio_helper.swift`.

Backends may produce partials/finals at different cadences, but they must join the same Pipeline → SegmentStore event path. Do not create a backend-specific subtitle or overlay path. In particular, a local Parakeet/MLX result must not bypass stable-prefix, segmentation, revision, display scheduling, records, or mode switching.

Relevant helpers:

- `stable_prefix.py`: stable ASR prefix calculation;
- `live_segmenter.py`: host-side sentence/semantic segmentation;
- `finalized_text.py`: final filtering and cleanup;
- `glossary.py`, `course_profiles.py`: conservative terminology and ASR correction support;
- `audio_formats.py`: input format normalization.

## Translation boundary

| Area | Code | Scope |
| --- | --- | --- |
| Local fastest draft | `fast_path.py`, `apple_translation.py`, `apple_translation_helper.swift` | Apple English → target language, no remote await |
| Preview scheduling | `translation_preview/` | bounded latest-wins remote preview; can be dropped |
| Context selection | `translation_context.py` | pure immutable snapshot/budget policy |
| Workflow selection | `translation_workflows/factory.py` | chooses portable Single Model, Apple only, or maintainer hybrid |
| Single Model | `translation_workflows/single_model.py`, `single_streaming.py` | portable OpenAI-compatible provider flow |
| Smart Hybrid | `translation_workflows/smart_hybrid.py`, `hybrid_translator.py` | maintainer-only multi-provider quota route |
| Optional bridge | `groq_bridge.py` | rapid optional preview, never final authority |
| Smart Hint | `smart_hint.py` | separate delayed topic/keyword background only |
| Usage/accounting | `translation_usage.py` | observational; must not affect provider timing |

`translation_context.py` is intentionally pure. It has no Qt, provider, network, config, or keychain imports. Context is frozen when a request is triggered, never when its worker happens to start. Keep Apple draft context at zero; do not make it wait for a cloud model, hint, record, or diagnostic.

`Smart Hybrid` and `Single Model` are separate products in the same runtime. Do not copy credentials, fallback state, or quota assumptions between them.

## Presentation boundary

| Output | Code | Notes |
| --- | --- | --- |
| Glass subtitle window | `overlay_window.py` | Qt output; text/history presentation only |
| Overlay creation | `overlay_factory.py` | central display-mode constructor |
| Native notch | `native_notch_overlay.py`, `native_notch/` Swift package | external native helper protocol |
| Overlay switching/lifecycle | `session_controller.py` | must not restart translation semantics |
| Window style/appearance | `dashboard_support/native_window_appearance.py` | dashboard-only native appearance |

The notch helper accepts presentation input; it does not own capture, ASR, remote requests, or segment IDs. For long sessions only recent visible records should be injected into the glass view. Complete classroom history belongs in the optional transcript store, not the renderer.

## Dashboard and settings

`dashboard.py` is the composition root for the PySide6 control center. Its support code is partially separated:

```text
dashboard_support/
  app_runtime.py               single-instance activation
  style.py / widgets.py        visual primitives
  workers.py                   short-lived non-Pipeline workers
  settings_snapshot.py         UI values captured as data
  settings_repository.py       config + Keychain save boundary
  provider_catalog.py          portable provider templates
  provider_profiles.py         named provider-profile metadata
  panels/                      gradually extracted page widgets
```

`SessionSettingsSnapshot` in `session_settings.py` is the running-session contract. Once Launch occurs, settings changes in the dashboard apply to the next Launch unless an action explicitly says otherwise. Never mutate a live Pipeline from a text field callback.

Secrets belong in `keychain_store.py`; never inspect or log local `config.ini` to diagnose an issue. Provider profile metadata may be stored locally, but plaintext API keys must not be committed, exported, benchmarked, or copied to the native App Store project.

## Records, diagnostics, and lifecycle

- `session_transcript_recorder.py` and `subtitle_record_store.py` persist finalized record material asynchronously. They cannot write on every partial.
- `runtime_log.py`, `runtime_performance.py`, and `tools/latency_baseline.py` are opt-in diagnostics. Diagnostics must remain off for normal classroom use.
- `permission_controller.py`, `shortcut_controller.py`, and `global_shortcut.py` own permission/hotkey behavior; they must not have a second Pipeline lifecycle path.
- `launcher.py`, `reloader.py`, `app_identity.py`, and `runtime_version.py` handle local launch identity only. They are not a notarized packaging system.

Pause must create a semantic boundary: clear finalized context, invalidate remote preview work, and reset Apple ASR without carrying a previous lecture fragment into the resumed one. Stop must release helper/capture processes and ensure stale remote completions cannot update a later session.

## Tests and verification map

```text
tests/unit/audio/          capture, Apple ASR, formats, optional ASR backends
tests/unit/subtitles/      events, segments, display, overlays, transcript store
tests/unit/translation/    FastPath, preview, context, workflows, usage
tests/unit/config/         config, keychain contract, runtime log
tests/unit/ui_logic/       dashboard support, shortcut, controllers, profiles
tests/integration/pipeline pipeline contracts
tests/integration/dashboard lifecycle and workflows
tests/integration/native_helpers helper source/capture contracts
tests/performance/         non-blocking performance expectations
```

Run the commands in `AGENT_HANDOFF.md` before a runtime change. If altering audio, Apple translation, subtitle events, overlay switching, or lifecycle, also do a 60–120 second system-audio manual smoke test with diagnostics. Do not run or alter the user's private course data, runtime logs, or keys as a test fixture.

## Safe continuation checklist

1. Read `AGENT_HANDOFF.md`, this file, and the specific module's existing tests before editing runtime code.
2. Identify whether the change belongs to capture, semantic state, translation policy, presentation, records, or dashboard. Do not cross those boundaries casually.
3. Add/adjust a domain test in the matching existing test directory; do not grow catch-all tests.
4. Confirm the Apple fast path remains independent and current.
5. Keep any new provider optional. API failure must leave local captions usable.
6. Update `AGENT_HANDOFF.md` if stage ordering, context, routing, or release verification changes. Add the change to `docs/development/CHANGELOG.md`.
7. For App Store work, move the feature design to the separate Swift project instead of making this prototype more packageable.

## Deliberate architectural boundaries

- This repository currently depends on Python and PySide6. It is a reference and migration source, not the macOS App Store target.
- The native Swift project intentionally begins from an Apple-only local baseline. Reusing an algorithm or public behavior is fine; linking this runtime or copying its credentials into the native app is not.
- Historical `course_profiles/` are generic public examples. User-specific courses, transcript files, and API credentials must stay outside commits.
