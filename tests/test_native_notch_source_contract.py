import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_PATH = os.path.join(
    ROOT,
    "native_notch",
    "Sources",
    "RealtimeNotchHelper",
    "main.swift",
)


class NativeNotchSourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SOURCE_PATH, encoding="utf-8") as handle:
            cls.source = handle.read()

    def test_all_display_counts_share_one_dynamic_notch_instance(self):
        self.assertIn("let notch = makeNotch", self.source)
        self.assertNotIn("smallNotch", self.source)
        self.assertNotIn("regularNotch", self.source)

    def test_subtitle_changes_use_opacity_without_directional_motion(self):
        self.assertIn(".transition(.opacity)", self.source)
        self.assertNotIn(".move(edge:", self.source)

    def test_mode_switch_holds_width_until_spring_finishes(self):
        self.assertIn("isChangingDisplayCount = true", self.source)
        self.assertIn(".spring(response: 0.30, dampingFraction: 0.88)", self.source)
        self.assertIn("Task.sleep(for: .seconds(0.30))", self.source)


if __name__ == "__main__":
    unittest.main()
