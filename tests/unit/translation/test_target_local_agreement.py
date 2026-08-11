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
