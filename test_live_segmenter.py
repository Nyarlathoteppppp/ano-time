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

    def test_long_stable_prefix_without_semantic_boundary_stays_partial(self):
        segmenter = IncrementalSegmenter()
        text = " ".join(f"word{i}" for i in range(24))
        finalized, remainder = segmenter.observe(text, stable_text=text, now=1)
        self.assertEqual(finalized, [])
        self.assertEqual(remainder, text)

    def test_elapsed_segment_age_does_not_cut_active_speech(self):
        segmenter = IncrementalSegmenter()
        text = "one two three four five six seven eight nine ten eleven twelve changing"
        segmenter.observe(text, stable_text="one two three", now=1)
        finalized, remainder = segmenter.observe(text, stable_text=" ".join(text.split()[:12]), now=3)
        self.assertEqual(finalized, [])
        self.assertEqual(remainder, text)

    def test_stalled_prefix_uses_safe_comma_boundary(self):
        segmenter = IncrementalSegmenter(timeout_seconds=1)
        text = "one two three four five six seven eight, Professor Smith explains the result"
        segmenter.observe(text, stable_text=text, now=1)
        finalized, remainder = segmenter.observe(text, now=2.1)
        self.assertEqual(finalized, ["one two three four five six seven eight,"])
        self.assertEqual(remainder, "Professor Smith explains the result")

    def test_lowercase_comma_continuation_is_not_a_semantic_boundary(self):
        segmenter = IncrementalSegmenter(timeout_seconds=1)
        text = (
            "Made in China became so successful that after just a few years, "
            "the government stopped using the term"
        )
        segmenter.observe(text, stable_text=text, now=1)
        finalized, remainder = segmenter.observe(text, now=2.1)
        self.assertEqual(finalized, [])
        self.assertEqual(remainder, text)

    def test_real_log_boundaries_are_not_split_mid_phrase(self):
        examples = [
            "Also the US and its allies have accused China of shortcutting some of its tech innovation by stealing intellectual property through hacking.",
            "Made in China 2025 got so successful that after just a few years, the government stopped using the term.",
            "The external threat forced them to pursue a self-sufficiency strategy in advanced technology.",
            "In 2023 it released a phone with a microchip far beyond what the rest of the world thought was possible.",
        ]
        forbidden_endings = (" by", " using", " pursue", " of the")
        for text in examples:
            segmenter = IncrementalSegmenter()
            finalized, _ = segmenter.observe(text, stable_text=text, now=4)
            self.assertFalse(
                any(part.casefold().endswith(forbidden_endings) for part in finalized),
                (text, finalized),
            )

    def test_final_emits_remaining_text_and_resets(self):
        segmenter = IncrementalSegmenter()
        finalized, remainder = segmenter.observe(
            "short final phrase", stable_text="", is_final=True, now=1
        )
        self.assertEqual(finalized, ["short final phrase"])
        self.assertEqual(remainder, "")
        self.assertEqual(segmenter.committed_words, 0)

    def test_native_final_keeps_long_unpunctuated_meaning_together(self):
        segmenter = IncrementalSegmenter()
        text = " ".join(f"technical{i}" for i in range(40))
        finalized, remainder = segmenter.observe(
            text, stable_text="", is_final=True, now=1
        )
        self.assertEqual(finalized, [text])
        self.assertEqual(remainder, "")


if __name__ == "__main__":
    unittest.main()
