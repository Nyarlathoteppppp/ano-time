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

    def test_compact_and_oldest_large_line_hide_english(self):
        self.assertIn("let hidesOriginal = displayCount == 1", self.source)
        self.assertIn("displayCount == 3 && item.id == visibleItems.first?.id", self.source)
        self.assertIn("if !hidesOriginal", self.source)

    def test_launch_and_exit_use_directional_notch_transitions(self):
        self.assertIn("openingAnimation: .easeOut(duration: 0.55)", self.source)
        self.assertIn("closingAnimation: .easeIn(duration: 0.28)", self.source)
        self.assertIn("skipIntermediateHides: true", self.source)
        self.assertIn("await expandActiveNotch()", self.source)
        self.assertNotIn("Task.sleep(for: .seconds(2.4))", self.source)
        self.assertIn("Task.sleep(for: .seconds(6))", self.source)
        self.assertIn("await compactActiveNotch()", self.source)
        self.assertIn(
            "hoverBehavior: [.hapticFeedback, .increaseShadow]", self.source
        )
        self.assertLess(
            self.source.index("await hideNotch()", self.source.index("func terminate")),
            self.source.index("emitEvent(event)", self.source.index("func terminate")),
        )

    def test_exit_cancels_pending_expansion_and_double_click_is_debounced(self):
        self.assertIn("notchTransitionTask?.cancel()", self.source)
        self.assertIn("state.compactTask?.cancel()", self.source)
        self.assertIn("guard !terminationInProgress else { return }", self.source)
        self.assertIn("now.timeIntervalSince(lastCycleAt) >= 0.25", self.source)

    def test_auto_compact_waits_for_finalized_idle_generation(self):
        self.assertIn("!state.hasActiveWork", self.source)
        self.assertIn(
            "state.subtitleGeneration == idleSubtitleGeneration", self.source
        )
        self.assertIn(
            "state.activityGeneration == idleActivityGeneration", self.source
        )
        self.assertIn("state.replaceItems", self.source)


if __name__ == "__main__":
    unittest.main()
