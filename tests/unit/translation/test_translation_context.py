import unittest

from translation_context import ContextPolicy, estimate_tokens


class ContextPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ContextPolicy()

    def test_first_preview_uses_one_prior_finalized_segment(self):
        context = self.policy.first_preview(
            ("oldest", "latest finalized"), live_hint="classification"
        )
        self.assertEqual(context.context_text, "latest finalized")
        self.assertEqual(context.previous_preview, "")
        self.assertEqual(context.live_hint, "classification")
        self.assertLessEqual(context.estimated_tokens, self.policy.PREVIEW_BUDGET)

    def test_first_preview_and_continuing_preview_have_different_draft_inputs(self):
        first = self.policy.first_preview(("previous English",))
        continuing = self.policy.continuing_preview(
            ("previous English",), previous_preview="已有中文"
        )
        self.assertEqual(first.previous_preview, "")
        self.assertEqual(continuing.previous_preview, "已有中文")

    def test_continuing_preview_keeps_draft_without_future_history(self):
        context = self.policy.continuing_preview(
            ("old", "prior finalized"),
            previous_preview="已有中文草稿",
        )
        self.assertEqual(context.context_text, "prior finalized")
        self.assertEqual(context.previous_preview, "已有中文草稿")

    def test_final_uses_three_prior_finalized_segments(self):
        context = self.policy.final(
            ("one", "two", "three", "four"),
            previous_preview="当前预览",
        )
        self.assertEqual(context.context_text, "two\nthree\nfour")
        self.assertEqual(context.previous_preview, "当前预览")
        self.assertLessEqual(context.estimated_tokens, self.policy.FINAL_BUDGET)

    def test_bridge_has_no_history_but_keeps_compact_live_hint(self):
        context = self.policy.bridge(live_hint="Fourier transform, FFT")
        self.assertEqual(context.context_text, "")
        self.assertEqual(context.previous_preview, "")
        self.assertEqual(context.live_hint, "Fourier transform, FFT")

    def test_long_optional_context_is_bounded_at_word_boundaries(self):
        history = (" ".join(f"word{index}" for index in range(600)),)
        context = self.policy.first_preview(history)
        self.assertTrue(context.truncated)
        self.assertIn("…", context.context_text)
        self.assertLessEqual(context.estimated_tokens, self.policy.PREVIEW_BUDGET)
        self.assertLessEqual(estimate_tokens(context.context_text), self.policy.PREVIEW_BUDGET)

    def test_empty_context_is_zero_cost(self):
        context = self.policy.final(())
        self.assertEqual(context.context_text, "")
        self.assertEqual(context.estimated_tokens, 0)

    def test_unspaced_chinese_preview_is_still_hard_bounded(self):
        context = self.policy.continuing_preview(
            (), previous_preview="翻译" * 500
        )
        self.assertTrue(context.truncated)
        self.assertLessEqual(context.estimated_tokens, self.policy.PREVIEW_BUDGET)


if __name__ == "__main__":
    unittest.main()
