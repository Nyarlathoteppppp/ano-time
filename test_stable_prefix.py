import unittest

from stable_prefix import StablePrefixTracker


class StablePrefixTrackerTests(unittest.TestCase):
    def test_confirms_shared_course_transcript_prefix(self):
        tracker = StablePrefixTracker(agreement_window=0.25, min_growth_words=3)

        self.assertIsNone(tracker.observe("The goal here is to find a model", now=0.0))
        self.assertIsNone(
            tracker.observe("The goal here is to find some sort of model", now=0.1)
        )
        self.assertEqual(
            tracker.observe(
                "The goal here is to find some sort of model for the data", now=0.3
            ),
            "The goal here is to find",
        )

    def test_ignores_case_and_punctuation_revisions(self):
        tracker = StablePrefixTracker(agreement_window=0.2, min_growth_words=3)
        tracker.observe("A heuristic is admissible", now=0.0)
        self.assertEqual(
            tracker.observe("a heuristic is admissible, if it never", now=0.25),
            "a heuristic is admissible",
        )

    def test_requires_meaningful_growth(self):
        tracker = StablePrefixTracker(agreement_window=0.2, min_growth_words=3)
        tracker.observe("probability density", now=0.0)
        self.assertIsNone(tracker.observe("probability density function", now=0.25))
        self.assertEqual(
            tracker.observe("probability density function describes data", now=0.5),
            "probability density function",
        )


if __name__ == "__main__":
    unittest.main()
