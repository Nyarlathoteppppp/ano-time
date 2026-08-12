import unittest

from subtitle_event import SubtitleEvent, SubtitleStage
from subtitle_presentation_coordinator import SubtitlePresentationCoordinator


class SubtitlePresentationCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.coordinator = SubtitlePresentationCoordinator(
            clock=lambda: self.now,
            ai_grace_seconds=0.9,
            max_ai_source_lag_words=8,
        )

    @staticmethod
    def event(
        revision,
        stage,
        source,
        target="",
        *,
        finalized=False,
        translation_source_text="",
    ):
        return SubtitleEvent.create(
            7,
            revision,
            stage,
            source,
            target,
            finalized=finalized,
            translation_source_text=translation_source_text,
        )

    def test_first_apple_draft_remains_immediate(self):
        event = self.event(
            1,
            SubtitleStage.APPLE_PARTIAL,
            "A heuristic",
            "启发式函数",
        )
        self.assertIs(self.coordinator.present(event), event)

    def test_ai_preview_owns_append_only_apple_and_asr_updates(self):
        short = "A heuristic estimates the cost"
        longer = short + " to reach the goal"
        apple = self.event(1, SubtitleStage.APPLE_PARTIAL, short, "苹果短草稿")
        preview = self.event(
            2, SubtitleStage.AI_PREVIEW, longer, "启发式函数估计代价",
            translation_source_text=short,
        )
        asr = self.event(3, SubtitleStage.ASR_PARTIAL, longer, "苹果长草稿")
        newer_apple = self.event(
            4, SubtitleStage.APPLE_PARTIAL, longer, "苹果长草稿"
        )

        self.coordinator.present(apple)
        self.coordinator.present(preview)
        asr_projection = self.coordinator.present(asr)
        self.assertEqual(asr_projection.translated_text, preview.translated_text)
        self.assertEqual(asr_projection.original_text, longer)
        self.assertEqual(asr_projection.stage, SubtitleStage.AI_PREVIEW)
        self.assertIsNone(self.coordinator.present(newer_apple))

    def test_slow_ai_releases_a_substantially_newer_apple_draft(self):
        short = "A heuristic estimates the cost"
        longer = short + " to reach the goal with an admissible estimate now"
        self.coordinator.present(
            self.event(1, SubtitleStage.APPLE_PARTIAL, short, "苹果短草稿")
        )
        self.coordinator.present(self.event(
            2, SubtitleStage.AI_PREVIEW, longer, "启发式函数估计代价",
            translation_source_text=short,
        ))
        self.now = 1.0
        released = self.coordinator.present(
            self.event(3, SubtitleStage.APPLE_PARTIAL, longer, "苹果长草稿")
        )
        self.assertIsNotNone(released)
        self.assertEqual(released.translated_text, "苹果长草稿")

    def test_late_ai_short_source_does_not_mask_apple_source_freshness(self):
        short = "we use a model"
        longer = short + " to estimate the expected loss over all data points today"
        self.coordinator.present(
            self.event(1, SubtitleStage.APPLE_PARTIAL, short, "苹果短草稿")
        )
        self.coordinator.present(self.event(
            2, SubtitleStage.AI_PREVIEW, longer, "我们使用模型",
            translation_source_text=short,
        ))
        self.now = 1.0
        released = self.coordinator.present(
            self.event(3, SubtitleStage.APPLE_PARTIAL, longer, "苹果长草稿")
        )
        self.assertEqual(released.translated_text, "苹果长草稿")

    def test_asr_rewrite_immediately_releases_current_apple_draft(self):
        old = "our wife variable is predicted"
        corrected = "our y variable is predicted"
        self.coordinator.present(
            self.event(1, SubtitleStage.APPLE_PARTIAL, old, "旧苹果草稿")
        )
        self.coordinator.present(
            self.event(2, SubtitleStage.AI_PREVIEW, old, "我们的目标变量")
        )
        released = self.coordinator.present(
            self.event(3, SubtitleStage.APPLE_PARTIAL, corrected, "y变量")
        )
        self.assertIsNotNone(released)
        self.assertEqual(released.translated_text, "y变量")

    def test_final_source_keeps_visible_preview_until_ai_final_arrives(self):
        source = "A heuristic estimates the cost to reach the goal"
        preview = self.event(
            1, SubtitleStage.AI_PREVIEW, source, "启发式函数估计到达目标的代价"
        )
        asr_final = self.event(
            2, SubtitleStage.ASR_FINAL, source, "苹果最终草稿", finalized=True
        )
        apple_final = self.event(
            3, SubtitleStage.APPLE_FINAL, source, "苹果最终草稿", finalized=True
        )
        ai_final = self.event(
            4, SubtitleStage.AI_FINAL, source, "启发式函数估计到达目标的实际代价", finalized=True
        )

        self.coordinator.present(preview)
        preserved = self.coordinator.present(asr_final)
        self.assertTrue(preserved.finalized)
        self.assertEqual(preserved.translated_text, preview.translated_text)
        self.assertIs(self.coordinator.present(apple_final), apple_final)
        self.assertIs(self.coordinator.present(ai_final), ai_final)

    def test_long_session_keeps_only_a_bounded_display_ownership_cache(self):
        coordinator = SubtitlePresentationCoordinator(
            retained_segment_count=4,
        )
        for segment_id in range(1, 12):
            coordinator.present(SubtitleEvent.create(
                segment_id,
                1,
                SubtitleStage.APPLE_FINAL,
                f"source {segment_id}",
                f"译文 {segment_id}",
                finalized=True,
            ))

        self.assertLessEqual(len(coordinator._segments), 4)
        self.assertNotIn(1, coordinator._segments)
        self.assertIn(11, coordinator._segments)


if __name__ == "__main__":
    unittest.main()
