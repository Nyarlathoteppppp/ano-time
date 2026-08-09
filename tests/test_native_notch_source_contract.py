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

    def test_mode_switch_shrinks_smoothly_but_grows_immediately(self):
        self.assertIn("isChangingDisplayCount = true", self.source)
        self.assertIn("if nextDisplayCount < displayCount", self.source)
        self.assertIn("withAnimation(.easeInOut(duration: 0.45))", self.source)
        self.assertIn("let isShrinking = width < contentWidth", self.source)
        self.assertIn("Task.sleep(for: .seconds(0.30))", self.source)

    def test_compact_mode_hides_english_and_does_not_measure_its_width(self):
        self.assertIn("if state.displayCount > 1", self.source)
        self.assertIn("let englishWidth = displayCount == 1 ? 0", self.source)

    def test_launch_and_exit_use_directional_notch_transitions(self):
        self.assertIn("openingAnimation: .easeOut(duration: 0.55)", self.source)
        self.assertIn("closingAnimation: .easeIn(duration: 0.28)", self.source)
        self.assertIn("skipIntermediateHides: true", self.source)
        self.assertIn("await expandActiveNotch()", self.source)
        self.assertNotIn("Task.sleep(for: .seconds(2.4))", self.source)
        self.assertNotIn("await compactActiveNotch()", self.source)
        self.assertIn(
            "hoverBehavior: [.hapticFeedback, .increaseShadow]", self.source
        )
        self.assertLess(
            self.source.index("await hideNotch()", self.source.index("func terminate")),
            self.source.index("emitEvent(event)", self.source.index("func terminate")),
        )


if __name__ == "__main__":
    unittest.main()
