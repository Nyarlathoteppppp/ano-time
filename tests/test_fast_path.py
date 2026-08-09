import threading
import unittest

from fast_path import FastPath
from segment_store import SegmentStore
from subtitle_event import SubtitleStage


class FastPathTests(unittest.TestCase):
    def test_only_latest_queued_partial_executes(self):
        store = SegmentStore()
        path = FastPath(store)
        started = threading.Event()
        release = threading.Event()
        completed = []

        def worker(value, block=False):
            if block:
                started.set()
                release.wait(timeout=1)
            completed.append(value)

        try:
            path.submit_partial(1, 1, worker, 1, True)
            self.assertTrue(started.wait(timeout=0.3))
            path.submit_partial(1, 2, worker, 2)
            latest = path.submit_partial(1, 3, worker, 3)
            release.set()
            latest.result(timeout=1)
            path.shutdown(wait=True)
        finally:
            release.set()

        self.assertEqual(completed, [1, 3])

    def test_final_rejects_running_partial_result(self):
        store = SegmentStore()
        store.publish(2, SubtitleStage.ASR_PARTIAL, "partial")
        hypothesis = store.hypothesis_revision(2)
        path = FastPath(store)
        started = threading.Event()
        release = threading.Event()
        results = []

        def partial_worker():
            started.set()
            release.wait(timeout=1)
            results.append(store.publish(
                2,
                SubtitleStage.APPLE_PARTIAL,
                "partial",
                "draft",
                expected_hypothesis=hypothesis,
            ))

        def final_worker():
            results.append(store.publish(
                2, SubtitleStage.APPLE_FINAL, "final", "final draft", True
            ))

        try:
            path.submit_partial(2, hypothesis, partial_worker)
            self.assertTrue(started.wait(timeout=0.3))
            store.publish(2, SubtitleStage.ASR_FINAL, "final", finalized=True)
            final = path.submit_final(2, final_worker)
            release.set()
            final.result(timeout=1)
            path.shutdown(wait=True)
        finally:
            release.set()

        self.assertIsNone(results[0])
        self.assertEqual(results[1].stage, SubtitleStage.APPLE_FINAL)


if __name__ == "__main__":
    unittest.main()
