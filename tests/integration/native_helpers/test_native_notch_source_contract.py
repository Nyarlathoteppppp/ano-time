import unittest

from tests.support.paths import project_path


SOURCE_PATH = project_path(
    "native_notch",
    "Sources",
    "RealtimeNotchHelper",
    "main.swift",
)


class NativeNotchSourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with SOURCE_PATH.open(encoding="utf-8") as handle:
            cls.source = handle.read()

    def test_all_display_counts_share_one_dynamic_notch_instance(self):
        self.assertIn("let notch = makeNotch", self.source)
        self.assertNotIn("smallNotch", self.source)
        self.assertNotIn("regularNotch", self.source)

    def test_subtitle_revisions_do_not_transition_the_entire_row(self):
        subtitle_content = self.source[
            self.source.index("private struct SubtitleContent"):
            self.source.index("private struct CompactLeading")
        ]
        self.assertNotIn(".transition(", subtitle_content)
        self.assertNotIn(".move(edge:", self.source)

    def test_authoritative_final_temporarily_holds_notch_width(self):
        self.assertIn("let authoritativeFinalRevision", self.source)
        self.assertIn("holdsFinalLayout = true", self.source)
        self.assertIn("Task.sleep(for: .seconds(0.40))", self.source)

    def test_streaming_text_anchors_single_line_growth_without_delaying_updates(self):
        self.assertIn("private struct StableStreamingText", self.source)
        self.assertIn("newText.hasPrefix(oldText)", self.source)
        self.assertIn("(newWidth - oldWidth) / 2", self.source)
        self.assertIn(".easeOut(duration: 0.11)", self.source)
        self.assertIn("immediate.disablesAnimations = true", self.source)
        streaming_source = self.source[
            self.source.index("private struct StableStreamingText"):
            self.source.index("private struct SubtitleContent")
        ]
        # Content is replaced synchronously.  The only delayed task clears the
        # short-lived changed-character tint and never gates subtitle text.
        self.assertLess(
            streaming_source.index("displayedText = newText"),
            streaming_source.index("Task.sleep"),
        )

    def test_streaming_translation_visually_separates_stable_prefix(self):
        self.assertIn("let committedPrefixLength: Int?", self.source)
        self.assertIn("private var styledText: Text", self.source)
        self.assertIn("String(run.text.prefix(stableCount))", self.source)
        self.assertIn("run.changed", self.source)
        self.assertIn(".bold()", self.source)
        self.assertIn(".white.opacity(0.82)", self.source)

    def test_streaming_translation_uses_local_character_revisions(self):
        self.assertIn("private func revisionRuns", self.source)
        self.assertIn("let nextRuns = revisionRuns", self.source)
        self.assertIn("displayedRuns = nextRuns", self.source)
        self.assertIn("let changed: Bool", self.source)

    def test_display_fragments_keep_a_stable_semantic_parent(self):
        self.assertIn("let fragments: [SubtitleFragment]?", self.source)
        self.assertIn("func visibleRows() -> [SubtitleFragment]", self.source)
        self.assertIn("items.map(\\.id) == newItems.map(\\.id)", self.source)

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

    def test_runtime_status_does_not_expand_notch_before_first_subtitle(self):
        self.assertIn("var hasSubtitleContent: Bool", self.source)
        self.assertIn("else if state.hasSubtitleContent", self.source)
        self.assertIn(
            "Runtime status frames arrive during initialization", self.source
        )

    def test_pause_compacts_immediately_without_idle_delay(self):
        pause_helper = self.source.index("func compactForPause")
        pause_compact = self.source.index("await compactActiveNotch()", pause_helper)
        helper_end = self.source.index("func terminate", pause_helper)

        self.assertLess(pause_compact, helper_end)
        self.assertNotIn(
            "Task.sleep", self.source[pause_helper:helper_end]
        )
        self.assertIn("compactForPause()", self.source)
        self.assertIn("if state.isPaused", self.source)
        self.assertIn("if !wasPaused", self.source)


if __name__ == "__main__":
    unittest.main()
