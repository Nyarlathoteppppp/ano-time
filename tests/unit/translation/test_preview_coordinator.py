import threading
import unittest

from translation_preview import ProgressivePreviewCoordinator


class ProgressivePreviewCoordinatorTests(unittest.TestCase):
    def test_active_survives_while_only_latest_pending_request_runs(self):
        events = []
        coordinator = ProgressivePreviewCoordinator(
            5, "test-preview", event_callback=lambda *args: events.append(args)
        )
        started = threading.Event()
        release = threading.Event()
        latest_finished = threading.Event()
        seen = []

        def worker(request):
            seen.append(request.source_text)
            if request.source_text == "active request":
                started.set()
                release.wait(timeout=1)
            if request.source_text == "latest pending":
                latest_finished.set()

        try:
            first = coordinator.submit(1, 1, "active request", worker)
            self.assertGreater(first.submitted_at, 0)
            self.assertGreater(first.deadline, first.submitted_at)
            self.assertTrue(started.wait(timeout=0.5))
            coordinator.submit(1, 2, "obsolete pending", worker)
            latest = coordinator.submit(1, 3, "latest pending", worker)
            self.assertTrue(coordinator.is_valid(first))
            self.assertTrue(coordinator.is_valid(latest))
            release.set()
            self.assertTrue(latest_finished.wait(timeout=0.5))
            self.assertNotIn("obsolete pending", seen)
            self.assertEqual(events[0][0], "superseded")
            self.assertEqual(events[0][1].source_text, "obsolete pending")
        finally:
            release.set()
            coordinator.shutdown()

    def test_invalidate_rejects_active_generation(self):
        coordinator = ProgressivePreviewCoordinator(5, "test-preview-reset")
        release = threading.Event()
        try:
            request = coordinator.submit(1, 1, "active", lambda _request: release.wait(1))
            coordinator.invalidate()
            self.assertFalse(coordinator.is_valid(request))
        finally:
            release.set()
            coordinator.shutdown()
