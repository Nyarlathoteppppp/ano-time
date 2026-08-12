import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import MethodType, SimpleNamespace

from main import Pipeline


class _Signal:
    def emit(self, *args):
        pass


class _AppleDraft:
    def translate(self, text):
        return f"draft:{text}"


class _BlockingAppleDraft:
    def __init__(self, started, release):
        self.started = started
        self.release = release

    def translate(self, text):
        self.started.set()
        self.release.wait(timeout=1)
        return f"draft:{text}"


class RealtimePriorityTests(unittest.TestCase):
    def test_final_translation_does_not_wait_for_groq_bridge(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.running = True
        pipeline.fast_translator = _AppleDraft()
        # The bridge is now an explicit workflow dependency instead of being
        # inferred from the final translator's provider pool.
        pipeline.bridge_translator = object()
        pipeline.signals = SimpleNamespace(runtime_status=_Signal())
        pipeline._emit_ranked_translation = lambda *args: True
        pipeline._submit_latest_ai = lambda *args: None
        pipeline._bridge_queue_lock = threading.RLock()
        pipeline._bridge_futures = {}

        bridge_started = threading.Event()
        release_bridge = threading.Event()

        def blocking_bridge(self, text, chunk_id, draft, deadline, context=None):
            bridge_started.set()
            release_bridge.wait(timeout=1)

        pipeline._run_groq_bridge = MethodType(blocking_bridge, pipeline)
        bridge_executor = ThreadPoolExecutor(max_workers=1)
        refine_executor = ThreadPoolExecutor(max_workers=1)
        try:
            started = time.perf_counter()
            pipeline._schedule_final_remote(
                "A useful finalized sentence",
                1,
                bridge_executor,
                refine_executor,
                "",
            )
            elapsed = time.perf_counter() - started
            self.assertTrue(bridge_started.wait(timeout=0.2))
            self.assertLess(elapsed, 0.1)
            self.assertFalse(release_bridge.is_set())
        finally:
            release_bridge.set()
            bridge_executor.shutdown(wait=True)
            refine_executor.shutdown(wait=True)

    def test_remote_paths_start_before_blocking_apple_final_returns(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.running = True
        apple_started = threading.Event()
        release_apple = threading.Event()
        ai_submitted = threading.Event()
        bridge_submitted = threading.Event()
        pipeline.fast_translator = _BlockingAppleDraft(apple_started, release_apple)
        pipeline.final_translator = object()
        pipeline.bridge_translator = object()
        pipeline.signals = SimpleNamespace(runtime_status=_Signal())
        pipeline._emit_ranked_translation = lambda *args: True
        pipeline._submit_latest_ai = lambda *args: ai_submitted.set()
        pipeline._submit_latest_bridge = lambda *args: bridge_submitted.set()

        bridge_executor = ThreadPoolExecutor(max_workers=1)
        refine_executor = ThreadPoolExecutor(max_workers=1)
        pipeline._schedule_final_remote(
            "A useful finalized sentence",
            1,
            bridge_executor,
            refine_executor,
            "",
        )
        thread = threading.Thread(
            target=pipeline._run_fast_final_translation,
            args=("A useful finalized sentence", 1),
        )
        try:
            thread.start()
            self.assertTrue(ai_submitted.wait(timeout=0.2))
            self.assertTrue(bridge_submitted.wait(timeout=0.2))
            self.assertTrue(apple_started.wait(timeout=0.2))
            self.assertTrue(thread.is_alive())
        finally:
            release_apple.set()
            thread.join(timeout=1)
            bridge_executor.shutdown(wait=True)
            refine_executor.shutdown(wait=True)

    def test_groq_bridge_keeps_only_latest_pending_segment(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline._bridge_queue_lock = threading.RLock()
        pipeline._bridge_futures = {}
        started = threading.Event()
        release = threading.Event()
        completed = []

        def bridge(self, text, chunk_id, draft, deadline, context=None):
            completed.append(chunk_id)
            if chunk_id == 1:
                started.set()
                release.wait(timeout=1)

        pipeline._run_groq_bridge = MethodType(bridge, pipeline)
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            pipeline._submit_latest_bridge(executor, "first sentence", 1, "draft 1")
            self.assertTrue(started.wait(timeout=0.2))
            pipeline._submit_latest_bridge(executor, "obsolete sentence", 2, "draft 2")
            pipeline._submit_latest_bridge(executor, "latest sentence", 3, "draft 3")
            release.set()
            executor.shutdown(wait=True)
            self.assertEqual(completed, [1, 3])
        finally:
            release.set()


if __name__ == "__main__":
    unittest.main()
