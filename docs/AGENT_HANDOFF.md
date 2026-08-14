# Anotime runtime handoff

Last verified baseline: `310c7f8` (`docs: define mac app store mvp plan`),
2026-08-14.  The active runtime uses the PySide6 `.venv-pyside` environment.

This document exists so future agents can safely continue work without
re-learning the real-time constraints from the codebase or changing a fast
path accidentally.

## Product priority

1. Show useful subtitles as early as possible.
2. Preserve translation correctness; remote finalization may correct previews.
3. Avoid visual churn, but never delay Apple ASR/Apple Translation merely to
   make the UI look smoother.
4. Remote providers are optional. A timeout, quota limit, or malformed custom
   API must leave the current Apple draft visible and allow later speech to
   continue.

## Runtime ownership

| Area | Primary code | Contract |
| --- | --- | --- |
| Pipeline lifecycle and Apple fast path | `main.py` | Apple ASR/Apple draft must not await remote futures. |
| Context selection | `translation_context.py` | Pure, deterministic, bounded, no Qt/network/provider imports. |
| Progressive remote preview | `translation_preview/` | Latest-wins scheduling; stale or expired work cannot publish. |
| Provider HTTP/prompt/accounting | `translator.py`, workflow/provider modules | Provider failure must not remove an Apple draft. |
| Subtitle ordering/visibility | subtitle event + presentation modules | A lower stage or older revision must not overwrite a newer one. |
| Native notch / glass renderers | native helper / Qt overlay code | Rendering is downstream only; it must not control translation scheduling. |

## Context policy (current behavior)

`ContextPolicy` in `translation_context.py` is the single source of truth.
It returns immutable `TranslationContext` objects. A request receives its
context **when it is triggered**, not when a worker eventually starts. This
prevents a queued preview from acquiring later lecture sentences.

| Request | History / previous draft | Budget | Notes |
| --- | --- | ---: | --- |
| Apple draft | None | 0 | Local fastest path; do not add context. |
| First AI Preview | Latest 1 finalized English sentence | 300 tokens | No previous Chinese preview. |
| Continuing AI Preview | Latest 1 finalized English + current Chinese preview | 300 tokens | Correctness overrides continuity. |
| Final refinement | Latest 3 finalized English + current Chinese preview | 800 tokens | Final can rewrite an incorrect preview. |
| Optional bridge | No lecture history; compact live hint only | 120 tokens | Keep it fast; it is optional. |
| Smart Hint | Latest 40 finalized English | Separate worker | Must never block normal translation. |

The stated budget covers added context, not the current source sentence or the
fixed prompt. Truncation prefers whole recent sentences; only an individually
oversized item is clipped at a word boundary.

Course topic and Smart Hint remain separate prompt inputs. A manually entered
topic replaces the default discipline background for the session; Smart Hint
adds temporary topic/keyword evidence. Neither changes the context history
policy. A newly launched app should start with an empty manually entered topic
unless the user fills it for that lecture.

## Course profiles

`course_profiles.py` discovers only explicit `course_profiles/*/profile.json`
assets. `course_profile_id` is selected in Home, saved in `config.ini`, and
captured at Launch. Never infer a profile from the session topic or live ASR:
that would leak a course-specific correction into unrelated speech.

- Profile names are generic and portable, never local course codes.
- A profile may add a local glossary, conservative finalized-ASR corrections,
  and a bounded current-sentence do-not-translate list.
- A manually entered lecture topic overrides the profile's generic domain for
  this launch; profile terminology remains active.
- Smart Hint is supplementary only. It cannot override CURRENT, the selected
  domain, or required terminology.
- Profile assets are repository examples only. Never import a user's private
  lecture transcripts from outside the project into the repository.

## Stage and routing invariants

```text
audio → Apple ASR partial → Apple Translation draft → visible subtitle
                                           ├→ optional bridge preview
                                           ├→ streaming AI preview
                                           └→ finalized English → final remote refinement
```

- Apple output is independent: never wait for Bridge, Preview, Final, Smart
  Hint, transcripts, diagnostics, or accounting.
- `latest-wins` only discards stale remote work. Do not apply it in a way that
  drops ordinary Apple partials; Apple calls are free and visual cadence is a
  product feature.
- Preview failures must not cool down or block the final Gemini → GLM/Qwen
  fallback route. Final failures may invoke the existing fallback rules.
- The hard remote deadline is a visibility boundary. A late answer can be
  saved to a transcript only if it cannot reclaim the currently visible newer
  subtitle.
- Smart Hybrid is maintainer-specific. Keep its credentials, quota management,
  and provider ordering isolated from portable Single Model behavior.

## Settings and secret handling

- API secrets belong in macOS Keychain. `config.ini` and provider profiles store
  Keychain references, not plaintext credentials.
- Runtime settings are captured at Launch. UI changes made while running must
  state “next Launch applies”; do not mutate a running Pipeline silently.
- Course topic is intentionally session-scoped and starts blank on a fresh app
  launch. Bridge enabled/disabled state can persist as a regular setting.
- Diagnostics are opt-in. Normal classroom use must not write runtime logs or
  run sampling threads.

## Required verification

### Always

```bash
./.venv-pyside/bin/python -m py_compile main.py dashboard.py translator.py translation_context.py translation_preview/*.py asr_pipeline/*.py
./tools/run_tests.sh
git diff --check
./.venv-pyside/bin/python tools/release_audit.py .
```

The native-notch and Parakeet verification checkpoint was 485 tests; the current
suite is 486 after the glass resize-grip regression contract.
Do not weaken or delete contracts just to make a refactor pass; move them to
the matching domain.

### When touching the live path

Run a real 60–120 second system-audio test with Diagnostics enabled, then
verify all of the following in the fresh runtime log:

- ScreenCaptureKit says `Ready` and Apple Speech says `ready`.
- Apple partial/final events continue while remote providers timeout or switch.
- Context stages report bounded `context_tokens`; queued previews retain the
  snapshot from their trigger point.
- Stop logs `Generator stopped`, `Capture stopped`, `Apple Speech: finished`,
  and `Pipeline Stopped`; no Pipeline/helper process remains.

The 2026-08-13 two-minute check captured 15 Apple final segments, bounded
Preview/Final contexts, and stopped cleanly. Gemini timeouts were correctly
discarded at the existing hard deadline; they did not interrupt the Apple
path.

### Manual UI release gate

Check microphone and system audio, `Control + S` launch/pause/resume, long
Chinese text in notch and glass modes, fullscreen video overlay, live mode
switching, and closing/returning to the control center. These behaviors cannot
be fully reproduced in headless unit tests.

For glass mode, also drag the visible lower-right `◢` grip, test a minimum-size
resize, and restart once to confirm `glass/geometry` is restored. The glass
renderer is a single chronological scroll projection: do not reintroduce a
fixed current-cue stage or a separately reflowed history region without a
real-macOS visual acceptance result.

## Known design boundaries (not automatically bugs)

- Apple Speech/Translation and ScreenCaptureKit require supported macOS
  versions and approved privacy permissions.
- Some custom OpenAI-compatible services do not support `stream=true`; Single
  Model falls back to a complete response, so it has no progressive remote
  preview on those services.
- Provider-reported token usage can be absent or inaccurate for custom APIs;
  the cost UI must label estimates honestly.
- The notch and glass layouts deliberately perform presentation-side smoothing.
  Do not “fix” visual motion by withholding Apple drafts or serializing remote
  translation work.
- Native notch keeps complete subtitle records in Python and renders a bounded
  Swift fragment projection. `NotchCue.displayWindow(for:)` shows the active
  cue's two newest fragments in source order (with a hidden-prefix marker) and
  a history cue's newest one; the SwiftUI layout must measure that same window.
  Do not treat display fragments as transcript records or semantic segments.
  Read `docs/development/NOTCH_LONG_TRANSLATION_DISPLAY_PLAN.md` before
  changing the window size, measurement, or Python IPC payload.
- Native notch transport is a separate live-path contract: helper startup must
  handshake before receiving a snapshot; frames require a generation and
  monotonic ID, and an unacknowledged helper restart must replay the current
  projection. Read `docs/development/NOTCH_TRANSPORT_RELIABILITY_PLAN.md`
  before changing the bridge, input loop, or notch animation triggers.
- Local ASR experiment: `native/parakeet_eou/` is an explicit FluidAudio
  CoreML/ANE **experimental** helper. On the 2026-08-13 same-audio benchmark
  its formal 50 ms-input helper produced the first English partial faster than
  Apple Speech, but used substantially more CPU/RAM and formed only one final
  over an uninterrupted 89.65-second lecture. Never make it the default or
  fallback automatically. Read `docs/LOCAL_ASR_BENCHMARK_2026-08-13.md` before
  changing ASR selection.
- `transcription.parakeet_adaptive_gain` is an explicit, default-off Parakeet
  input preconditioner. It only raises weak non-silent PCM before the Parakeet
  helper and never starts Apple ASR, changes Apple/MLX audio, VAD, translation
  or capture. Keep Apple and Parakeet sequential for comparisons; do not add
  a concurrent Apple fallback without a new benchmark and plan.
- Existing MLX Whisper is a rolling re-transcription backend, not native
  token-streaming. It has better controlled SML/AI Planning term coverage but
  materially higher latency and memory use than Apple Speech.
- A Parakeet host semantic boundary is a candidate, not an immediate semantic
  final. It seals only after two stable observations and 350 ms. A later native
  source-final can correct a sealed segment under the same ID; SegmentStore and
  Pipeline must keep rejecting old-source translations and replace, rather than
  append, finalized context. The implementation currently supports same-segment
  token replacements only; use a trace and new tests before attempting
  cross-boundary insertions/deletions.

## Update this handoff when

Update this file in the same commit whenever you change:

- Subtitle stage ordering or stale-result rules.
- Context inputs, budgets, snapshot timing, or Smart Hint behavior.
- Provider routing/fallback/deadline semantics.
- Keychain/config persistence behavior.
- Required test commands or real-device release checks.

## Maintenance record

Use [`docs/development/MAINTENANCE_PROTOCOL.md`](development/MAINTENANCE_PROTOCOL.md)
for every development batch. Append the verified result to
`docs/development/CHANGELOG.md`; do not put user-local settings, logs,
credentials, or lecture text in either document.
For branch, Issue, PR, Actions and release rules, also follow
[`docs/development/GITHUB_WORKFLOW.md`](development/GITHUB_WORKFLOW.md).
# Current engineering handoff

## Unified ASR event pipeline

- Canonical design: `docs/development/UNIFIED_ASR_EVENT_PIPELINE_PLAN.md`.
- Completed: protocol/acceptance safety net, Apple-equivalent migration,
  Parakeet EOU semantic-boundary policy, and MLX rolling-output migration in
  `ASRSubtitleCoordinator`.
- Apple runtime remains the latency baseline. Its source callback is adapted by
  `StreamingASRAdapter`; translation, display and recording continue through
  the existing Pipeline outputs.
- Do **not** add another subtitle route for Apple, Parakeet or MLX. All three
  emit immutable ASR events into the shared coordinator.
- MLX uses `RollingASRAdapter`: sequence and anchor are frozen when an audio
  snapshot is submitted, not when inference completes. Its pause boundary
  invalidates outstanding snapshots before starting a fresh stream.
- Whisper and FunASR remain explicitly legacy paths. Do not migrate either by
  copying MLX code; create their adapter contract and real-audio baseline first.
- Native Apple and Parakeet helpers have process-generation guards. Preserve
  them whenever changing their reset/start lifecycle.
- Native notch helper startup is also an acknowledged snapshot protocol:
  `ready` → latest complete `generation` / `frameId` snapshot → `applied`.
  Status frames intentionally carry the same bounded snapshot, and Swift must
  ignore equal snapshots without restarting layout or notch transitions.

## Verification performed

- Full PySide6 suite passed after the Phase-3 migration: 465 tests.
- Focused protocol/Pipeline tests passed: 34 tests.
- 60-second real system-audio Apple smoke test: six native finals, 573 signal
  updates, no Pipeline error. Apple Translation availability can independently
  depend on macOS language resources.
- MLX replay smoke test using captured system audio: seven ASR partials, two
  ASR finals, seven Apple drafts and two Apple finals across two segments; no
  Pipeline error.
- 2026-08-14 current batch: full PySide6 suite 485/485, native-notch targeted
  contracts 53/53, release `RealtimeNotchHelper` build, Swift planner target,
  `git diff --check` and release secret audit passed. The new native IPC and
  Parakeet weak-input path still require device validation; no classroom audio
  or user-local configuration is recorded in this repository.

## Next safe step

Run the native-notch 60–120 second device scenario in
[`docs/development/NOTCH_TRANSPORT_RELIABILITY_PLAN.md`](development/NOTCH_TRANSPORT_RELIABILITY_PLAN.md),
checking `notch_transport` ready / queued / written / applied events through
notch → glass → notch. Then continue Parakeet work with Phase 3 then Phase 4 in
[`docs/development/PARAKEET_RELIABILITY_PLAN.md`](development/PARAKEET_RELIABILITY_PLAN.md).
Do not tune EOU or host-boundary thresholds without the prescribed replay
measurements, and do not promote Parakeet beyond experimental status before
the real-device acceptance criteria pass. The correction implementation covers
same-segment word replacements only. Phase 4 of the unified migration remains
limited to real-device acceptance, a support matrix, and removal of genuinely
unreachable MLX-specific subtitle code. Do not modify the legacy
Whisper/FunASR output path opportunistically.
