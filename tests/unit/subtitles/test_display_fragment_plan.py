import unittest

from display_fragment_plan import DisplayFragmentPlan


def split_every_five(text):
    text = str(text or "")
    return [text[index:index + 5] for index in range(0, len(text), 5)] or [""]


class DisplayFragmentPlanTests(unittest.TestCase):
    def test_append_keeps_completed_fragments_exactly_stable(self):
        plan = DisplayFragmentPlan()
        initial = plan.project(7, "abcdefghij", split_every_five)
        grown = plan.project(7, "abcdefghijklmno", split_every_five)

        self.assertEqual(initial, ["abcde", "fghij"])
        self.assertEqual(grown[:2], initial)
        self.assertEqual(grown[-1], "klmno")

    def test_small_append_continues_the_existing_tail_before_creating_a_row(self):
        plan = DisplayFragmentPlan()
        plan.project(7, "abcdefg", split_every_five)
        grown = plan.project(7, "abcdefghi", split_every_five)

        self.assertEqual(grown, ["abcde", "fghi"])

    def test_rewrite_replaces_old_fragments_to_keep_current_text_correct(self):
        plan = DisplayFragmentPlan()
        plan.project(7, "abcdefghij", split_every_five)
        corrected = plan.project(7, "abcdeZ", split_every_five)

        self.assertEqual(corrected, ["abcde", "Z"])

    def test_tail_correction_keeps_only_the_exact_completed_prefix(self):
        plan = DisplayFragmentPlan()
        plan.project(7, "abcdefghij", split_every_five)
        corrected = plan.project(7, "abcdeXYZ", split_every_five)

        self.assertEqual(corrected, ["abcde", "XYZ"])

    def test_retain_bounds_visual_cache_to_visible_semantic_cues(self):
        plan = DisplayFragmentPlan()
        plan.project(1, "first", split_every_five)
        plan.project(2, "second", split_every_five)
        plan.retain([2])

        self.assertNotIn(1, plan._states)
        self.assertIn(2, plan._states)


if __name__ == "__main__":
    unittest.main()
