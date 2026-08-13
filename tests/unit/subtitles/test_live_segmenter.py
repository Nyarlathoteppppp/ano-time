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

    def test_stalled_prefix_never_finalizes_at_comma(self):
        segmenter = IncrementalSegmenter(timeout_seconds=1)
        text = "one two three four five six seven eight, Professor Smith explains the result"
        segmenter.observe(text, stable_text=text, now=1)
        finalized, remainder = segmenter.observe(text, now=2.1)
        self.assertEqual(finalized, [])
        self.assertEqual(remainder, text)

    def test_stalled_prefix_can_finalize_at_semicolon(self):
        segmenter = IncrementalSegmenter(timeout_seconds=1)
        text = "one two three four five six seven eight; Professor Smith explains the result"
        segmenter.observe(text, stable_text=text, now=1)
        finalized, remainder = segmenter.observe(text, now=2.1)
        self.assertEqual(finalized, ["one two three four five six seven eight;"])
        self.assertEqual(remainder, "Professor Smith explains the result")

    def test_conditional_clause_before_comma_is_not_finalized(self):
        segmenter = IncrementalSegmenter(timeout_seconds=1)
        text = "If you see the initial misconception in earlier days, I'm not telling every engineer did it"
        segmenter.observe(text, stable_text=text, now=1)
        finalized, remainder = segmenter.observe(text, now=2.1)
        self.assertEqual(finalized, [])
        self.assertEqual(remainder, text)

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

    def test_host_mode_splits_before_a_stable_discourse_starter(self):
        segmenter = IncrementalSegmenter(host_semantic_boundaries=True)
        text = (
            "The compressed representation preserves the important structure "
            "of the original data but the decoder needs additional information"
        )
        finalized, remainder = segmenter.observe(text, stable_text=text, now=1)

        self.assertEqual(
            finalized,
            ["The compressed representation preserves the important structure of the original data"],
        )
        self.assertEqual(remainder, "but the decoder needs additional information")
        self.assertEqual(segmenter.last_cut_reasons, ["host_discourse_boundary"])

    def test_host_mode_never_splits_before_a_dependent_because_clause(self):
        segmenter = IncrementalSegmenter(host_semantic_boundaries=True)
        text = (
            "The compressed representation preserves the important structure "
            "of the original data because the decoder needs additional information"
        )
        finalized, remainder = segmenter.observe(text, stable_text=text, now=1)

        self.assertEqual(finalized, [])
        self.assertEqual(remainder, text)

    def test_host_mode_never_splits_before_so_that(self):
        segmenter = IncrementalSegmenter(host_semantic_boundaries=True)
        text = (
            "The algorithm stores a compact representation of the input data "
            "so that the decoder can recover the required information"
        )
        finalized, remainder = segmenter.observe(text, stable_text=text, now=1)

        self.assertEqual(finalized, [])
        self.assertEqual(remainder, text)

    def test_host_mode_uses_a_content_word_window_only_after_long_growth(self):
        segmenter = IncrementalSegmenter(
            host_semantic_boundaries=True,
            target_words=12,
            host_force_words=20,
        )
        text = (
            "The encoder creates a compact representation preserving useful "
            "structure while allowing the decoder to reconstruct important "
            "details from the observed data without extra metadata"
        )
        finalized, remainder = segmenter.observe(text, stable_text=text, now=1)

        self.assertEqual(len(finalized), 1)
        self.assertLess(len(finalized[0].split()), 20)
        self.assertFalse(finalized[0].endswith(("of", "the", "in", "a", "to")))
        self.assertTrue(remainder)
        self.assertEqual(segmenter.last_cut_reasons, ["host_stable_window"])

    def test_host_window_never_cuts_at_a_preposition_or_determiner(self):
        segmenter = IncrementalSegmenter(
            host_semantic_boundaries=True,
            target_words=10,
            host_force_words=18,
        )
        text = (
            "The model estimates the probability of the next token in the "
            "sequence using a representation of the observed context"
        )
        finalized, _remainder = segmenter.observe(text, stable_text=text, now=1)

        self.assertEqual(len(finalized), 1)
        self.assertFalse(finalized[0].endswith(("of", "the", "in", "a")))


if __name__ == "__main__":
    unittest.main()
