import unittest

from finalized_text import clean_finalized_text, is_meaningful_final, should_request_remote


class FinalizedTextTests(unittest.TestCase):
    def test_cleans_streaming_repetitions(self):
        self.assertEqual(clean_finalized_text("if you if you wanted to"), "if you wanted to")
        self.assertEqual(clean_finalized_text("put them into into that"), "put them into that")
        self.assertEqual(clean_finalized_text("informal, informal way"), "informal way")

    def test_preserves_intentional_emphasis(self):
        self.assertEqual(clean_finalized_text("really, really small"), "really, really small")
        self.assertEqual(clean_finalized_text("very very useful"), "very very useful")

    def test_filters_only_punctuation_from_finalized_pipeline(self):
        self.assertFalse(is_meaningful_final("..."))
        self.assertTrue(is_meaningful_final("AdaGrad."))

    def test_short_final_uses_local_translation_without_remote_request(self):
        self.assertFalse(should_request_remote("Yes."))
        self.assertFalse(should_request_remote("Is that clear?"))
        self.assertTrue(should_request_remote("This is a convex function."))


if __name__ == "__main__":
    unittest.main()
