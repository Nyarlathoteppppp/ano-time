import unittest

from live_segmenter import IncrementalSegmenter


class IncrementalSegmenterTest(unittest.TestCase):
    def test_short_partial_is_not_committed(self):
        segmenter = IncrementalSegmenter()
        finalized, remainder = segmenter.observe(
            "A heuristic estimates remaining cost", stable_text="A heuristic estimates"
        )
        self.assertEqual(finalized, [])
        self.assertEqual(remainder, "A heuristic estimates remaining cost")

    def test_stable_sentence_boundary_commits_early(self):
        segmenter = IncrementalSegmenter()
        text = "A heuristic estimates the remaining cost to a goal. It may be admissible"
        finalized, remainder = segmenter.observe(text, stable_text=text, now=1)
        self.assertEqual(finalized, ["A heuristic estimates the remaining cost to a goal."])
        self.assertEqual(remainder, "It may be admissible")

    def test_boundary_survives_stable_prefix_without_trailing_period(self):
        segmenter = IncrementalSegmenter()
        text = "A heuristic estimates the remaining cost to a goal. It may change"
        stable = "A heuristic estimates the remaining cost to a goal"
        finalized, remainder = segmenter.observe(text, stable_text=stable, now=1)
        self.assertEqual(finalized, ["A heuristic estimates the remaining cost to a goal."])
        self.assertEqual(remainder, "It may change")

    def test_long_stable_prefix_is_cut_near_target(self):
        segmenter = IncrementalSegmenter()
        text = " ".join(f"word{i}" for i in range(24))
        finalized, remainder = segmenter.observe(text, stable_text=text, now=1)
        self.assertEqual(len(finalized[0].split()), 16)
        self.assertEqual(len(remainder.split()), 8)

    def test_timeout_commits_only_a_substantial_stable_prefix(self):
        segmenter = IncrementalSegmenter()
        text = "one two three four five six seven eight nine ten eleven twelve changing"
        segmenter.observe(text, stable_text="one two three", now=1)
        finalized, remainder = segmenter.observe(text, stable_text=" ".join(text.split()[:12]), now=3)
        self.assertEqual(len(finalized[0].split()), 12)
        self.assertEqual(remainder, "changing")

    def test_final_emits_remaining_text_and_resets(self):
        segmenter = IncrementalSegmenter()
        finalized, remainder = segmenter.observe(
            "short final phrase", stable_text="", is_final=True, now=1
        )
        self.assertEqual(finalized, ["short final phrase"])
        self.assertEqual(remainder, "")
        self.assertEqual(segmenter.committed_words, 0)


if __name__ == "__main__":
    unittest.main()
