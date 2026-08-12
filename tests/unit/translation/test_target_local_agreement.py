import unittest

from translation_preview import TargetLocalAgreement


class TargetLocalAgreementTests(unittest.TestCase):
    def test_first_candidate_is_visible_immediately(self):
        agreement = TargetLocalAgreement(holdback_characters=4)
        projection = agreement.observe(1, "为了实现这一点，需要调用模型")
        self.assertTrue(projection.accepted)
        self.assertEqual(projection.display_text, "为了实现这一点，需要调用模型")
        self.assertEqual(projection.committed_prefix, "")

    def test_repeated_prefix_is_committed_with_mutable_tail(self):
        agreement = TargetLocalAgreement(holdback_characters=4)
        agreement.observe(1, "为了实现这一点，需要调用模型")
        projection = agreement.observe(1, "为了实现这一点，需要调用准备好的模型")
        self.assertTrue(projection.accepted)
        self.assertTrue(projection.committed_prefix.startswith("为了实现这一点"))
        self.assertLess(len(projection.committed_prefix), len(projection.display_text))

    def test_stream_updates_do_not_commit_until_complete_candidate(self):
        agreement = TargetLocalAgreement(holdback_characters=0)
        agreement.project_stream(1, "为了")
        streamed = agreement.project_stream(1, "为了实现这一点")
        self.assertEqual(streamed.committed_prefix, "")
        completed = agreement.observe(1, "为了实现这一点，需要模型")
        self.assertEqual(completed.committed_prefix, "")

    def test_divergent_preview_cannot_rewrite_committed_prefix(self):
        agreement = TargetLocalAgreement(holdback_characters=0)
        first = agreement.observe(1, "稳定前缀和旧尾部")
        agreement.observe(1, "稳定前缀和新尾部")
        rejected = agreement.observe(1, "完全不同的开头")
        self.assertFalse(rejected.accepted)
        self.assertNotEqual(rejected.display_text, "完全不同的开头")
        self.assertNotEqual(first.display_text, "")

    def test_exposes_last_displayed_candidate_as_an_immutable_snapshot(self):
        agreement = TargetLocalAgreement()
        self.assertEqual(agreement.displayed_candidate(8), "")
        agreement.project_stream(8, "上一版预览")
        self.assertEqual(agreement.displayed_candidate(8), "上一版预览")
        agreement.reset(8)
        self.assertEqual(agreement.displayed_candidate(8), "")

    def test_never_commits_the_middle_of_an_english_word(self):
        agreed = TargetLocalAgreement.agreed_prefix(
            "the covariance matrix", "the covariate changed", 0
        )
        self.assertEqual(agreed, "the")

    def test_keeps_a_complete_english_word_and_exposes_three_states(self):
        agreement = TargetLocalAgreement(holdback_characters=0)
        agreement.observe(1, "the covariance matrix")
        projection = agreement.observe(1, "the covariance matrix is useful")
        self.assertEqual(projection.stable_prefix, "the covariance matrix")
        self.assertEqual(projection.mutable_tail, " is useful")

    def test_does_not_commit_an_unclosed_latex_expression(self):
        agreed = TargetLocalAgreement.agreed_prefix(
            r"the value is $\\hat{\\alpha}",
            r"the value is $\\hat{\\alpha}_i$",
            0,
        )
        self.assertEqual(agreed, "the value is")
