import unittest

from translation_preview import PreviewTriggerPolicy


class PreviewTriggerPolicyTests(unittest.TestCase):
    def test_triggers_at_first_threshold_then_only_after_source_growth(self):
        policy = PreviewTriggerPolicy(
            first_words=6, growth_words=6, minimum_interval=0.6
        )
        six = " ".join(f"word{i}" for i in range(6))
        self.assertTrue(policy.should_request(1, six, now=1.0))
        self.assertFalse(policy.should_request(1, six, now=2.0))
        self.assertFalse(policy.should_request(1, six + " more", now=2.0))
        twelve = " ".join(f"word{i}" for i in range(12))
        self.assertTrue(policy.should_request(1, twelve, now=2.0))

    def test_new_segment_resets_and_punctuation_can_trigger_early(self):
        policy = PreviewTriggerPolicy()
        self.assertTrue(policy.should_request(7, "This clause ends here;", now=1.0))
        self.assertTrue(policy.should_request(8, "Another clause ends here;", now=1.1))

    def test_corrected_requested_prefix_can_trigger_without_six_more_words(self):
        policy = PreviewTriggerPolicy(first_words=6, growth_words=6)
        self.assertTrue(policy.should_request(1, "our wife variable predicts this value", now=1))
        self.assertTrue(policy.should_request(1, "our y variable predicts this value", now=1.1))
