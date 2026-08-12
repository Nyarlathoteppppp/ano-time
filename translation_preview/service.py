"""Provider-agnostic orchestration for progressive remote translations."""

import time

from runtime_log import log_stage
from subtitle_event import SubtitleStage

from .agreement import TargetLocalAgreement
from .coordinator import ProgressivePreviewCoordinator
from .trigger_policy import PreviewTriggerPolicy


class ProgressiveTranslationPreview:
    """Run optional bridge and final-model previews outside finalization."""

    def __init__(
        self,
        *,
        emit_subtitle,
        segment_store,
        bridge_client,
        final_client,
        bridge_gate,
        context_snapshot,
        is_active,
        status_callback=None,
    ):
        self._emit_subtitle = emit_subtitle
        self._segment_store = segment_store
        self._bridge_client = bridge_client
        self._final_client = final_client
        self._bridge_gate = bridge_gate
        self._context_snapshot = context_snapshot
        self._is_active = is_active
        self._status_callback = status_callback or (lambda *_args: None)
        self._agreement = TargetLocalAgreement()
        self._bridge_policy = PreviewTriggerPolicy(
            first_words=4,
            growth_words=9,
            minimum_interval=0.8,
        )
        self._final_policy = PreviewTriggerPolicy(
            first_words=5,
            growth_words=6,
            minimum_interval=0.6,
        )
        self._bridge_coordinator = ProgressivePreviewCoordinator(
            1.2,
            "bridge-preview",
        )
        self._final_coordinator = ProgressivePreviewCoordinator(
            1.25,
            "final-model-preview",
            event_callback=self._on_final_coordinator_event,
        )

    @staticmethod
    def _on_final_coordinator_event(event, request):
        if event == "superseded":
            log_stage(
                "preview_superseded",
                chunk_id=request.segment_id,
                status="dropped",
                words=len(request.source_text.split()),
                hypothesis_revision=request.hypothesis_revision,
            )

    def observe(
        self,
        segment_id,
        hypothesis_revision,
        source_text,
        stable_source_text="",
    ):
        """Observe one ASR hypothesis without blocking its caller."""
        if not self._is_active():
            return
        bridge = self._bridge_client()
        if (
            bridge is not None
            and stable_source_text
            and self._bridge_policy.should_request(
                segment_id,
                stable_source_text,
            )
        ):
            self._bridge_coordinator.submit(
                segment_id,
                hypothesis_revision,
                stable_source_text,
                self._run_bridge,
            )
            log_stage(
                "bridge_preview_trigger",
                chunk_id=segment_id,
                words=len(stable_source_text.split()),
                hypothesis_revision=hypothesis_revision,
            )
        if (
            self._final_client() is not None
            and self._final_policy.should_request(segment_id, source_text)
        ):
            self._final_coordinator.submit(
                segment_id,
                hypothesis_revision,
                source_text,
                self._run_final_model,
            )
            log_stage(
                "ai_preview_trigger",
                chunk_id=segment_id,
                words=len(source_text.split()),
                hypothesis_revision=hypothesis_revision,
            )
            self._status_callback("active", "ON · translating")

    def _compatible(self, request):
        return (
            self._is_active()
            and time.monotonic() < request.deadline
            and self._segment_store.preview_is_compatible(
                request.segment_id,
                request.hypothesis_revision,
                request.source_text,
            )
        )

    def _run_bridge(self, request):
        if not self._bridge_coordinator.is_valid(request) or not self._compatible(request):
            return
        translator = self._bridge_client()
        if translator is None:
            return
        allowed, reason = self._bridge_gate.allow(request.source_text)
        if not allowed:
            log_stage(
                "bridge_preview",
                chunk_id=request.segment_id,
                status="skipped",
                detail=reason,
            )
            return
        try:
            started = time.perf_counter()
            translated = translator.translate(
                request.source_text,
                use_context=False,
                remember_context=False,
                deadline=request.deadline,
            )
            if (
                not translated
                or not self._bridge_coordinator.is_valid(request)
                or not self._compatible(request)
            ):
                log_stage(
                    "bridge_preview",
                    chunk_id=request.segment_id,
                    status="dropped_stale",
                )
                return
            emitted = self._emit_subtitle(
                request.segment_id,
                request.source_text,
                translated,
                "partial",
                SubtitleStage.BRIDGE_PREVIEW,
                expected_hypothesis=request.hypothesis_revision,
                translation_rank=2,
                translation_source_text=request.source_text,
            )
            log_stage(
                "bridge_preview",
                chunk_id=request.segment_id,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                status="shown" if emitted else "dropped_stale",
                detail=translated,
            )
        except Exception as exc:
            log_stage(
                "bridge_preview",
                chunk_id=request.segment_id,
                status="error",
                detail=str(exc),
            )

    def _run_final_model(self, request):
        queue_wait_ms = (time.monotonic() - request.submitted_at) * 1000
        log_stage(
            "ai_preview_queue",
            chunk_id=request.segment_id,
            elapsed_ms=queue_wait_ms,
            words=len(request.source_text.split()),
        )
        def request_is_current():
            return (
                time.monotonic() < request.deadline
                and self._final_coordinator.is_valid(request)
                and self._compatible(request)
            )

        if not request_is_current():
            log_stage(
                "preview_stale_result",
                chunk_id=request.segment_id,
                status="dropped",
                hypothesis_revision=request.hypothesis_revision,
            )
            return
        translator = self._final_client()
        if translator is None:
            return
        previous_preview = self._agreement.displayed_candidate(
            request.segment_id
        )

        started = time.perf_counter()
        first_display_logged = False

        def publish(candidate, commit_candidate=False):
            nonlocal first_display_logged
            if (
                not candidate
                or not request_is_current()
            ):
                return False
            projection = (
                self._agreement.observe(request.segment_id, candidate)
                if commit_candidate
                else self._agreement.project_stream(request.segment_id, candidate)
            )
            if not projection.accepted or not projection.display_text:
                return False
            emitted = bool(self._emit_subtitle(
                request.segment_id,
                request.source_text,
                projection.display_text,
                "partial",
                SubtitleStage.AI_PREVIEW,
                expected_hypothesis=request.hypothesis_revision,
                translation_rank=3,
                translation_source_text=request.source_text,
                committed_prefix_length=len(projection.committed_prefix),
            ))
            if emitted and not first_display_logged:
                first_display_logged = True
                log_stage(
                    "ai_preview_first",
                    chunk_id=request.segment_id,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    queue_wait_ms=queue_wait_ms,
                    total_ms=(
                        queue_wait_ms
                        + (time.perf_counter() - started) * 1000
                    ),
                    words=len(request.source_text.split()),
                )
                self._status_callback(
                    "ok",
                    f"ON · {(time.perf_counter() - started):.1f}s",
                )
            return emitted

        try:
            translated = translator.translate(
                request.source_text,
                use_context=False,
                remember_context=False,
                previous_preview=previous_preview or None,
                prefer_preview_continuity=True,
                context_text=self._context_snapshot(),
                deadline=request.deadline,
                failure_scope="preview",
                on_update=lambda candidate: publish(candidate, False),
            )
            if time.monotonic() >= request.deadline:
                log_stage(
                    "preview_deadline",
                    chunk_id=request.segment_id,
                    status="returned_late",
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                )
                return
            shown = publish(translated, True)
            if not shown and not request_is_current():
                log_stage(
                    "preview_stale_result",
                    chunk_id=request.segment_id,
                    status="dropped",
                    hypothesis_revision=request.hypothesis_revision,
                )
            log_stage(
                "ai_preview",
                chunk_id=request.segment_id,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                status="shown" if shown else "streamed_or_stale",
                words=len(request.source_text.split()),
                detail=translated or "",
            )
        except TimeoutError as exc:
            self._status_callback("warning", "ON · preview timeout")
            log_stage(
                "ai_preview",
                chunk_id=request.segment_id,
                status="timeout",
                detail=str(exc),
            )
            log_stage(
                "preview_deadline",
                chunk_id=request.segment_id,
                status="dropped",
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            self._status_callback("error", "ON · preview failed")
            log_stage(
                "ai_preview",
                chunk_id=request.segment_id,
                status="error",
                detail=str(exc),
            )

    def reset_if_source_rewritten(self, segment_id, previous_state, source_text):
        if (
            previous_state.translation_stage == SubtitleStage.AI_PREVIEW
            and previous_state.translation_source_text
            and not source_text.startswith(previous_state.translation_source_text)
        ):
            self._agreement.reset(segment_id)

    def finalize(self, segment_id):
        self._agreement.reset(segment_id)

    def displayed_candidate(self, segment_id):
        """Snapshot the visible preview before finalization resets agreement."""
        return self._agreement.displayed_candidate(segment_id)

    def reset(self):
        self._bridge_policy.reset()
        self._final_policy.reset()
        self._bridge_coordinator.invalidate()
        self._final_coordinator.invalidate()
        self._agreement.reset()

    def shutdown(self):
        self._bridge_coordinator.shutdown()
        self._final_coordinator.shutdown()
        self._agreement.reset()
