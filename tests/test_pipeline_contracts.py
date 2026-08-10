import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import MethodType, SimpleNamespace

from main import (
    Pipeline,
    WorkerSignals,
    diagnostic_audio_activity_threshold,
    recent_audio_anchor,
)
from subtitle_event import SubtitleStage


class RecordingSignal:
    def __init__(self):
        self.events = []

    def emit(self, *args):
        self.events.append(args)


class PipelineContractTests(unittest.TestCase):
    def test_diagnostic_audio_anchor_accepts_quiet_recent_speech_only(self):
        self.assertAlmostEqual(
            diagnostic_audio_activity_threshold(0.005), 0.00175
        )
        self.assertEqual(recent_audio_anchor(10.0, 11.4), 10.0)
        self.assertIsNone(recent_audio_anchor(10.0, 11.6))

    def test_start_runs_processing_loop_on_daemon_thread(self):
        pipeline = Pipeline.__new__(Pipeline)
        ran = threading.Event()
        pipeline.processing_loop = ran.set

        pipeline.start()

        self.assertTrue(ran.wait(timeout=0.5))
        pipeline.thread.join(timeout=0.5)
        self.assertTrue(pipeline.thread.daemon)

    def test_stop_releases_audio_thread_and_fast_translator(self):
        calls = []
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.running = True
        pipeline.audio = SimpleNamespace(stop=lambda: calls.append("audio"))
        pipeline.fast_translator = SimpleNamespace(
            stop=lambda: calls.append("fast_translator")
        )
        pipeline.thread = SimpleNamespace(
            is_alive=lambda: True,
            join=lambda timeout: calls.append(("join", timeout)),
        )

        pipeline.stop()

        self.assertFalse(pipeline.running)
        self.assertEqual(
            calls,
            ["audio", ("join", 2), "fast_translator"],
        )

    def test_pause_and_resume_are_immediate_and_monotonic(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline._paused = threading.Event()

        pipeline.set_paused(True)
        self.assertTrue(pipeline.is_paused)
        pipeline.set_paused(False)
        self.assertFalse(pipeline.is_paused)

    def test_pause_seals_boundary_and_resets_apple_session_in_background(self):
        boundary_called = threading.Event()
        reset_called = threading.Event()
        pipeline = Pipeline.__new__(Pipeline)
        pipeline._paused = threading.Event()
        pipeline._pause_boundary_handler = boundary_called.set
        pipeline._fast_path = SimpleNamespace(invalidate_all=lambda: None)
        pipeline.apple_transcriber = SimpleNamespace(reset=reset_called.set)
        pipeline._apple_reset_thread = None

        pipeline.set_paused(True)

        self.assertTrue(boundary_called.wait(timeout=0.2))
        self.assertTrue(reset_called.wait(timeout=0.5))
        self.assertTrue(pipeline.is_paused)

    def test_partial_apple_groq_ai_order_cannot_regress(self):
        updates = RecordingSignal()
        pipeline = Pipeline.__new__(Pipeline)
        pipeline._paused = threading.Event()
        pipeline._translation_state_lock = threading.Lock()
        pipeline._translation_ranks = {}
        pipeline.signals = SimpleNamespace(update_text=updates)

        updates.emit(7, "partial English", "Apple partial", "partial")
        self.assertTrue(pipeline._emit_ranked_translation(7, "final", "Apple", "final", 1))
        self.assertTrue(pipeline._emit_ranked_translation(7, "final", "Groq", "final", 2))
        self.assertTrue(pipeline._emit_ranked_translation(7, "final", "AI", "final", 3))
        self.assertFalse(pipeline._emit_ranked_translation(7, "final", "late Groq", "final", 2))
        self.assertFalse(pipeline._emit_ranked_translation(7, "final", "late Apple", "final", 1))

        self.assertEqual(
            [event[2] for event in updates.events],
            ["Apple partial", "Apple", "Groq", "AI"],
        )

    def test_ai_queue_keeps_two_active_and_only_latest_pending(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline._refine_queue_lock = threading.RLock()
        pipeline._refine_futures = {}
        started = []
        both_started = threading.Event()
        release = threading.Event()
        completed = []

        def worker(self, text, chunk_id, context, deadline):
            started.append(chunk_id)
            if len(started) == 2:
                both_started.set()
            release.wait(timeout=1)
            completed.append(chunk_id)

        pipeline._run_refinement = MethodType(worker, pipeline)
        executor = ThreadPoolExecutor(max_workers=2)
        try:
            pipeline._submit_latest_ai(executor, pipeline._run_refinement, "one", 1, "")
            pipeline._submit_latest_ai(executor, pipeline._run_refinement, "two", 2, "")
            self.assertTrue(both_started.wait(timeout=0.5))
            pipeline._submit_latest_ai(executor, pipeline._run_refinement, "obsolete", 3, "")
            pipeline._submit_latest_ai(executor, pipeline._run_refinement, "latest", 4, "")
            release.set()
            executor.shutdown(wait=True)
            self.assertEqual(sorted(completed), [1, 2, 4])
        finally:
            release.set()

    def test_expired_ai_deadline_never_calls_provider_or_updates_ui(self):
        updates = RecordingSignal()
        provider = SimpleNamespace(
            translate=lambda *_args, **_kwargs: self.fail("provider called after deadline")
        )
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.running = True
        pipeline.translator = provider
        pipeline.signals = SimpleNamespace(
            update_text=updates,
            runtime_status=RecordingSignal(),
        )

        pipeline._run_refinement(
            "A finalized sentence",
            9,
            "",
            time.monotonic() - 0.001,
        )

        self.assertEqual(updates.events, [])

    def test_typed_subtitle_events_increment_revision_and_feed_legacy_signal(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.signals = WorkerSignals()
        typed = []
        legacy = []
        pipeline.signals.subtitle_event.connect(typed.append)
        pipeline.signals.update_text.connect(lambda *args: legacy.append(args))

        first = pipeline._emit_subtitle(
            12, "A partial", "一个草稿", "partial", SubtitleStage.APPLE_PARTIAL
        )
        second = pipeline._emit_subtitle(
            12, "A final", "一个终稿", "final", SubtitleStage.AI_FINAL
        )

        self.assertEqual([event.revision for event in typed], [1, 2])
        self.assertEqual(first.stage, SubtitleStage.APPLE_PARTIAL)
        self.assertFalse(first.finalized)
        self.assertEqual(second.stage, SubtitleStage.AI_FINAL)
        self.assertTrue(second.finalized)
        self.assertEqual(
            legacy,
            [
                (12, "A partial", "一个草稿", "partial"),
                (12, "A final", "一个终稿", "final"),
            ],
        )

    def test_pipeline_adapter_rejects_stale_apple_partial(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.signals = WorkerSignals()
        typed = []
        pipeline.signals.subtitle_event.connect(typed.append)

        pipeline._emit_subtitle(
            20, "A heuristic", "", "partial", SubtitleStage.ASR_PARTIAL
        )
        old_hypothesis = pipeline._segment_state_store().hypothesis_revision(20)
        pipeline._emit_subtitle(
            20,
            "A heuristic is admissible",
            "",
            "partial",
            SubtitleStage.ASR_PARTIAL,
        )
        stale = pipeline._emit_subtitle(
            20,
            "A heuristic",
            "一种启发式方法",
            "partial",
            SubtitleStage.APPLE_PARTIAL,
            expected_hypothesis=old_hypothesis,
        )

        self.assertIsNone(stale)
        self.assertEqual(len(typed), 2)
        self.assertEqual(typed[-1].original_text, "A heuristic is admissible")


if __name__ == "__main__":
    unittest.main()
