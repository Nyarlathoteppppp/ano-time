import unittest

from segment_store import SegmentStore
from subtitle_event import SubtitleStage


class SegmentStoreTests(unittest.TestCase):
    def test_prefix_compatible_apple_partial_survives_newer_hypothesis(self):
        store = SegmentStore()
        first = store.publish(1, SubtitleStage.ASR_PARTIAL, "A heuristic")
        first_hypothesis = store.hypothesis_revision(1)
        second = store.publish(1, SubtitleStage.ASR_PARTIAL, "A heuristic is admissible")

        compatible = store.publish(
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
        self.assertIsNotNone(compatible)
        self.assertEqual(compatible.original_text, "A heuristic is admissible")
        self.assertEqual(compatible.translated_text, "一种启发式方法")
        self.assertEqual(current.revision, 4)

    def test_corrected_source_rejects_incompatible_apple_partial(self):
        store = SegmentStore()
        store.publish(2, SubtitleStage.ASR_PARTIAL, "our wife variable")
        hypothesis = store.hypothesis_revision(2)
        store.publish(2, SubtitleStage.ASR_PARTIAL, "our y variable is predicted")

        stale = store.publish(
            2,
            SubtitleStage.APPLE_PARTIAL,
            "our wife variable",
            "我们的妻子变量",
            expected_hypothesis=hypothesis,
        )

        self.assertIsNone(stale)
        self.assertEqual(store.snapshot(2).original_text, "our y variable is predicted")

    def test_source_correction_immediately_clears_incompatible_apple_draft(self):
        store = SegmentStore()
        old = "our wife variable"
        store.publish(9, SubtitleStage.ASR_PARTIAL, old)
        store.publish(
            9,
            SubtitleStage.APPLE_PARTIAL,
            old,
            "我们的妻子变量",
            expected_hypothesis=store.hypothesis_revision(9),
        )

        corrected = store.publish(
            9,
            SubtitleStage.ASR_PARTIAL,
            "our y variable is predicted",
        )

        self.assertEqual(corrected.translated_text, "")
        self.assertIsNone(store.snapshot(9).translation_stage)

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

    def test_bridge_preview_does_not_finalize_or_block_new_source_hypotheses(self):
        store = SegmentStore()
        stable = "A heuristic estimates the remaining cost"
        store.publish(5, SubtitleStage.ASR_PARTIAL, stable)
        hypothesis = store.hypothesis_revision(5)
        preview = store.publish(
            5,
            SubtitleStage.BRIDGE_PREVIEW,
            stable,
            "启发式函数估计剩余代价",
            expected_hypothesis=hypothesis,
            translation_source_text=stable,
        )
        self.assertIsNotNone(preview)
        self.assertFalse(preview.finalized)

        longer = stable + " to reach the goal"
        source_update = store.publish(5, SubtitleStage.ASR_PARTIAL, longer)
        self.assertEqual(source_update.original_text, longer)
        self.assertEqual(source_update.translated_text, "启发式函数估计剩余代价")
        self.assertFalse(store.snapshot(5).finalized)

    def test_corrected_prefix_invalidates_old_preview_and_rejects_late_result(self):
        store = SegmentStore()
        old = "round or my swan fits the model"
        store.publish(6, SubtitleStage.ASR_PARTIAL, old)
        hypothesis = store.hypothesis_revision(6)
        store.publish(
            6,
            SubtitleStage.BRIDGE_PREVIEW,
            old,
            "错误预览",
            expected_hypothesis=hypothesis,
            translation_source_text=old,
        )
        corrected = "run ordinary least squares to fit the model"
        store.publish(6, SubtitleStage.ASR_PARTIAL, corrected)

        self.assertFalse(store.preview_is_compatible(6, hypothesis, old))
        late = store.publish(
            6,
            SubtitleStage.BRIDGE_PREVIEW,
            old,
            "迟到错误预览",
            expected_hypothesis=hypothesis,
            translation_source_text=old,
        )
        self.assertIsNone(late)

    def test_ai_preview_overrides_bridge_but_does_not_finalize(self):
        store = SegmentStore()
        source = "A model predicts the target variable"
        store.publish(8, SubtitleStage.ASR_PARTIAL, source)
        hypothesis = store.hypothesis_revision(8)
        store.publish(
            8,
            SubtitleStage.BRIDGE_PREVIEW,
            source,
            "模型预测目标",
            expected_hypothesis=hypothesis,
            translation_source_text=source,
        )
        preview = store.publish(
            8,
            SubtitleStage.AI_PREVIEW,
            source,
            "模型会预测目标变量",
            expected_hypothesis=hypothesis,
            translation_source_text=source,
        )
        late_bridge = store.publish(
            8,
            SubtitleStage.BRIDGE_PREVIEW,
            source,
            "迟到的桥接翻译",
            expected_hypothesis=hypothesis,
            translation_source_text=source,
        )

        self.assertFalse(preview.finalized)
        self.assertIsNone(late_bridge)
        self.assertEqual(store.snapshot(8).translated_text, "模型会预测目标变量")

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
