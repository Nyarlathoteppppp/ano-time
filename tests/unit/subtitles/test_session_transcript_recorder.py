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

    def test_existing_records_are_kept_permanently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "AnoTime_2026-01-01_00-00-00_双语记录.txt"
            unrelated = root / "lecture.txt"
            for path in (old, unrelated):
                path.write_text("test", encoding="utf-8")
            now = 1_786_300_000

            recorder = SessionTranscriptRecorder(
                directory, now=lambda: now, flush_delay=0
            )
            recorder.stop()

            self.assertTrue(old.exists())
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

    def test_finalized_ai_stream_is_not_written_until_ai_final(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = SessionTranscriptRecorder(directory, flush_delay=0)
            recorder.update_event(SubtitleEvent.create(
                3,
                4,
                SubtitleStage.AI_STREAM,
                "A finalized source sentence",
                "仍在逐字生成",
                finalized=True,
            ))
            recorder.update_event(SubtitleEvent.create(
                3,
                5,
                SubtitleStage.AI_FINAL,
                "A finalized source sentence",
                "最终译文",
                finalized=True,
            ))
            recorder.stop()

            content = recorder.path.read_text(encoding="utf-8")
            self.assertNotIn("仍在逐字生成", content)
            self.assertIn("译文：最终译文", content)

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
