import os
from pathlib import Path
import tempfile
import unittest

from session_transcript_recorder import SessionTranscriptRecorder
from subtitle_event import SubtitleEvent, SubtitleStage


class SessionTranscriptRecorderTests(unittest.TestCase):
    def test_session_file_contains_latest_aligned_original_and_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = SessionTranscriptRecorder(
                directory, now=lambda: 1_786_300_000, flush_delay=0
            )
            recorder.update_text(1, "A heuristic is admissible.", "启发式是可采纳的。")
            recorder.update_text(1, "A heuristic is admissible.", "启发式函数是可采纳的。", "final")
            recorder.stop()

            content = recorder.path.read_text(encoding="utf-8")
            self.assertIn("日期：", content)
            self.assertIn("开始时间：", content)
            self.assertIn("原文：A heuristic is admissible.", content)
            self.assertIn("译文：启发式函数是可采纳的。", content)
            self.assertEqual(content.count("原文：A heuristic is admissible."), 1)

    def test_cleanup_removes_only_expired_anotime_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "AnoTime_2026-01-01_00-00-00_双语记录.txt"
            recent = root / "AnoTime_2026-08-09_00-00-00_双语记录.txt"
            unrelated = root / "lecture.txt"
            for path in (old, recent, unrelated):
                path.write_text("test", encoding="utf-8")
            now = 1_786_300_000
            os.utime(old, (now - 4 * 86400, now - 4 * 86400))
            os.utime(recent, (now - 86400, now - 86400))

            recorder = SessionTranscriptRecorder(
                directory, now=lambda: now, flush_delay=0
            )
            recorder.stop()

            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(unrelated.exists())

    def test_typed_preview_is_not_persisted_as_final_record(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = SessionTranscriptRecorder(directory, flush_delay=0)
            recorder.update_event(SubtitleEvent.create(
                1,
                1,
                SubtitleStage.AI_PREVIEW,
                "A growing source prefix",
                "一段增长中的预览",
                finalized=False,
            ))
            recorder.stop()

            content = recorder.path.read_text(encoding="utf-8")
            self.assertNotIn("一段增长中的预览", content)

    def test_asr_final_does_not_promote_visible_preview_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = SessionTranscriptRecorder(directory, flush_delay=0)
            recorder.update_event(SubtitleEvent.create(
                2,
                2,
                SubtitleStage.ASR_FINAL,
                "A complete source sentence",
                "仍然只是预览",
                finalized=True,
            ))
            recorder.stop()

            content = recorder.path.read_text(encoding="utf-8")
            self.assertIn("原文：A complete source sentence", content)
            self.assertNotIn("仍然只是预览", content)


if __name__ == "__main__":
    unittest.main()
