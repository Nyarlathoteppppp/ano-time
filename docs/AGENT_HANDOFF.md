# Anotime runtime handoff

Last verified: `91b6443` (`docs: map legacy prototype architecture`).

This document exists so future agents can safely continue work without
re-learning the real-time constraints from the codebase or changing a fast
path accidentally.

For a module-by-module map of this Python/PySide6 prototype, read
[`ARCHITECTURE_MAP.md`](ARCHITECTURE_MAP.md). The native App Store product is a
separate Swift repository and must not be coupled to this runtime.

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
python3 -m py_compile main.py translator.py translation_context.py translation_preview/*.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -q
git diff --check
```

The suite was 414 tests at the 2026-08-14 verification. Do not weaken or delete
contracts just to make a refactor pass; move them to the matching domain.

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

## Update this handoff when

Update this file in the same commit whenever you change:

- Subtitle stage ordering or stale-result rules.
- Context inputs, budgets, snapshot timing, or Smart Hint behavior.
- Provider routing/fallback/deadline semantics.
- Keychain/config persistence behavior.
- Required test commands or real-device release checks.
