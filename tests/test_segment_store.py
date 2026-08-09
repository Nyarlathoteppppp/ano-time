import unittest

from segment_store import SegmentStore
from subtitle_event import SubtitleStage


class SegmentStoreTests(unittest.TestCase):
    def test_stale_apple_partial_is_rejected_after_new_hypothesis(self):
        store = SegmentStore()
        first = store.publish(1, SubtitleStage.ASR_PARTIAL, "A heuristic")
        first_hypothesis = store.hypothesis_revision(1)
        second = store.publish(1, SubtitleStage.ASR_PARTIAL, "A heuristic is admissible")

        stale = store.publish(
            1,
            SubtitleStage.APPLE_PARTIAL,
            "A heuristic",
            "一种启发式方法",
            expected_hypothesis=first_hypothesis,
        )
        current = store.publish(
            1,
            SubtitleStage.APPLE_PARTIAL,
            "A heuristic is admissible",
            "一种启发式方法是可采纳的",
            expected_hypothesis=store.hypothesis_revision(1),
        )

        self.assertEqual(first.revision, 1)
        self.assertEqual(second.revision, 2)
        self.assertIsNone(stale)
        self.assertEqual(current.revision, 3)

    def test_repeated_asr_text_does_not_invalidate_visible_apple_draft(self):
        store = SegmentStore()
        store.publish(3, SubtitleStage.ASR_PARTIAL, "same hypothesis")
        hypothesis = store.hypothesis_revision(3)
        store.publish(
            3,
            SubtitleStage.APPLE_PARTIAL,
            "same hypothesis",
            "相同的假设",
            expected_hypothesis=hypothesis,
        )

        repeated = store.publish(
            3, SubtitleStage.ASR_PARTIAL, "same hypothesis"
        )

        self.assertIsNone(repeated)
        self.assertEqual(store.hypothesis_revision(3), hypothesis)
        self.assertEqual(store.snapshot(3).translated_text, "相同的假设")

    def test_finalization_invalidates_inflight_partial(self):
        store = SegmentStore()
        store.publish(4, SubtitleStage.ASR_PARTIAL, "partial")
        hypothesis = store.hypothesis_revision(4)
        final = store.publish(4, SubtitleStage.ASR_FINAL, "final", finalized=True)
        late = store.publish(
            4,
            SubtitleStage.APPLE_PARTIAL,
            "partial",
            "迟到草稿",
            expected_hypothesis=hypothesis,
        )

        self.assertTrue(final.finalized)
        self.assertIsNone(late)
        self.assertTrue(store.snapshot(4).finalized)

    def test_translation_stage_never_regresses(self):
        store = SegmentStore()
        store.publish(7, SubtitleStage.ASR_FINAL, "final", finalized=True)
        self.assertIsNotNone(store.publish(
            7, SubtitleStage.APPLE_FINAL, "final", "Apple", True
        ))
        self.assertIsNotNone(store.publish(
            7, SubtitleStage.GROQ_BRIDGE, "final", "Groq", True
        ))
        self.assertIsNotNone(store.publish(
            7, SubtitleStage.AI_STREAM, "final", "AI stream", True
        ))
        self.assertIsNotNone(store.publish(
            7, SubtitleStage.AI_FINAL, "final", "AI final", True
        ))
        self.assertIsNone(store.publish(
            7, SubtitleStage.AI_STREAM, "final", "late stream", True
        ))
        self.assertIsNone(store.publish(
            7, SubtitleStage.GROQ_BRIDGE, "final", "late Groq", True
        ))
        self.assertEqual(store.snapshot(7).translated_text, "AI final")


if __name__ == "__main__":
    unittest.main()
