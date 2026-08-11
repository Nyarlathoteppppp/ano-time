import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from subtitle_display_scheduler import SubtitleDisplayScheduler
from subtitle_event import SubtitleEvent, SubtitleStage


class SubtitleDisplaySchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def event(revision, text, stage=SubtitleStage.AI_PREVIEW, finalized=False):
        return SubtitleEvent.create(
            1, revision, stage, "source", text, finalized=finalized
        )

    def test_leading_update_is_immediate_and_burst_keeps_latest(self):
        shown = []
        scheduler = SubtitleDisplayScheduler(shown.append, interval_ms=30)
        scheduler.submit(self.event(1, "第"))
        scheduler.submit(self.event(2, "第一"))
        scheduler.submit(self.event(3, "第一版"))
        self.assertEqual([event.revision for event in shown], [1])

        deadline = time.monotonic() + 0.2
        while len(shown) < 2 and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertEqual([event.revision for event in shown], [1, 3])

    def test_default_stream_cadence_is_110_ms(self):
        scheduler = SubtitleDisplayScheduler(lambda _event: None)
        self.assertAlmostEqual(scheduler.interval_seconds, 0.110, places=3)

    def test_stage_change_and_final_are_immediate(self):
        shown = []
        scheduler = SubtitleDisplayScheduler(shown.append, interval_ms=100)
        scheduler.submit(self.event(1, "Apple", SubtitleStage.APPLE_PARTIAL))
        scheduler.submit(self.event(2, "Gemini", SubtitleStage.AI_PREVIEW))
        scheduler.submit(self.event(3, "Final", SubtitleStage.AI_FINAL, True))
        self.assertEqual([event.revision for event in shown], [1, 2, 3])

    def test_asr_final_flag_does_not_disable_ai_stream_coalescing(self):
        shown = []
        scheduler = SubtitleDisplayScheduler(shown.append, interval_ms=100)
        scheduler.submit(self.event(1, "第", SubtitleStage.AI_STREAM, True))
        scheduler.submit(self.event(2, "第一", SubtitleStage.AI_STREAM, True))
        scheduler.submit(self.event(3, "第一版", SubtitleStage.AI_STREAM, True))
        self.assertEqual([event.revision for event in shown], [1])


if __name__ == "__main__":
    unittest.main()
