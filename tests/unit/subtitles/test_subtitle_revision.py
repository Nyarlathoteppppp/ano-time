import unittest

from subtitle_revision import SubtitleRevisionPlanner


class SubtitleRevisionPlannerTests(unittest.TestCase):
    def test_preserves_equal_middle_run_and_changes_only_surrounding_words(self):
        revision = SubtitleRevisionPlanner.plan(
            "这个人很喜欢吃西瓜。",
            "小花狗很喜欢吃草莓。",
        )

        stable = "".join(span.text for span in revision.spans if not span.changed)
        changed = [span.text for span in revision.spans if span.changed]
        self.assertIn("很喜欢吃", stable)
        self.assertIn("小花狗", changed)
        self.assertIn("草莓", changed)
        self.assertEqual(
            "".join(span.text for span in revision.spans),
            "小花狗很喜欢吃草莓。",
        )

    def test_first_render_is_not_marked_as_a_revision(self):
        revision = SubtitleRevisionPlanner.plan("", "第一次翻译")
        self.assertTrue(all(not span.changed for span in revision.spans))


if __name__ == "__main__":
    unittest.main()
