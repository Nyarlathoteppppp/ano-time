import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.qt import QtCore, QtWidgets

QRect = QtCore.QRect
QApplication = QtWidgets.QApplication
QScrollBar = QtWidgets.QScrollBar

from overlay_window import (
    GLASS_CURRENT_GROWTH_CUSHION,
    GLASS_PANEL_BACKGROUND,
    GLASS_TAIL_SCROLL_SLACK,
    MAX_VISIBLE_TRANSCRIPT_ITEMS,
    LogItem,
    OverlayWindow,
    clamp_window_rect,
)


class OverlayLayoutTests(unittest.TestCase):
    def test_empty_translation_shows_only_the_english_row(self):
        item = LogItem(1, "00:00:00", "English arrives first", "")
        self.assertFalse(item.original_label.isHidden())
        self.assertTrue(item.translated_label.isHidden())
        self.assertEqual(item.translated_label.text(), "")

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_middle_long_translation_allocates_every_wrapped_line(self):
        item = LogItem(
            2,
            "00:00:00",
            "A long technical sentence about infrastructure and oil reserves.",
            "这是一段位于中间的长中文翻译，"
            "在狭窄的玻璃字幕窗口内会换成多行。"
            "后面还有新字幕时，本段最后一行也不能被下一段遮住。",
            finalized=True,
        )
        item.resize(290, 100)
        item.refresh_layout()
        margins = item.layout.contentsMargins()
        self.assertEqual(margins.bottom(), 15)
        available = item.width() - margins.left() - margins.right()

        self.assertEqual(
            item.translated_label.height(),
            item.translated_label.heightForWidth(available),
        )
        required = (
            margins.top() + margins.bottom()
            + item.original_label.height()
            + item.translated_label.height()
            + max(0, item.layout.spacing())
        )
        self.assertEqual(item.height(), required)

    def test_restored_window_is_moved_back_from_disconnected_display(self):
        clamped = clamp_window_rect(
            QRect(3000, 200, 500, 400),
            [QRect(0, 0, 1440, 900)],
        )
        self.assertEqual(clamped, QRect(940, 200, 500, 400))

    def test_restored_window_is_reduced_to_available_screen(self):
        clamped = clamp_window_rect(
            QRect(-100, -100, 3000, 2000),
            [QRect(0, 0, 1440, 900)],
        )
        self.assertEqual(clamped, QRect(0, 0, 1440, 900))

    def test_valid_geometry_on_secondary_screen_is_preserved(self):
        original = QRect(1600, 100, 500, 400)
        clamped = clamp_window_rect(
            original,
            [QRect(0, 0, 1440, 900), QRect(1440, 0, 1440, 900)],
        )
        self.assertEqual(clamped, original)

    def test_glass_panel_uses_seventy_percent_opaque_neutral_background(self):
        self.assertEqual(GLASS_PANEL_BACKGROUND, "rgba(0, 0, 0, 179)")

        class Container:
            def setStyleSheet(self, stylesheet):
                self.stylesheet = stylesheet

        view = SimpleNamespace(container=Container())
        OverlayWindow._set_glass_style(view)

        self.assertIn(GLASS_PANEL_BACKGROUND, view.container.stylesheet)
        self.assertIn("border-radius: 20px", view.container.stylesheet)

    def test_direct_glass_window_does_not_activate_legacy_qt_notch(self):
        with patch("overlay_window.HAS_APPKIT", False):
            window = OverlayWindow(
                window_width=480,
                window_height=260,
                display_mode="glass",
                allow_notch_switch=False,
            )
        try:
            window.container.mode_switch_requested.emit()
            self.assertEqual(window.display_mode, "glass")
            self.assertFalse(hasattr(window.container, "notch_mode"))
        finally:
            window.close()

    def test_reversible_glass_window_forwards_subtitle_double_click_request(self):
        with patch("overlay_window.HAS_APPKIT", False):
            window = OverlayWindow(
                window_width=480,
                window_height=260,
                display_mode="glass",
                allow_notch_switch=True,
            )
        requested = []
        window.notch_requested.connect(lambda: requested.append(True))
        try:
            # The surface owns the subtitle area, which is the actual double-
            # click target in the visible glass overlay.
            window.container.mode_switch_requested.emit()
            self.assertEqual(requested, [True])
        finally:
            window.close()

    def test_glass_window_relies_on_automatic_recording_without_manual_save(self):
        with patch("overlay_window.HAS_APPKIT", False):
            window = OverlayWindow(window_width=480, window_height=260)
        try:
            self.assertFalse(hasattr(window, "save_btn"))
            self.assertFalse(hasattr(window, "_save_transcript"))
            self.assertIsNotNone(window.stop_btn)
            self.assertIsNotNone(window.mode_btn)
        finally:
            window.close()

    def test_glass_window_has_a_visible_bottom_right_resize_grip(self):
        with patch("overlay_window.HAS_APPKIT", False):
            window = OverlayWindow(window_width=480, window_height=260)
        try:
            window.resize(520, 300)
            # Hidden Qt widgets do not consistently emit resizeEvent in the
            # offscreen test backend, so exercise the layout method directly.
            window._layout_resize_borders()

            grip = window.resize_handle
            self.assertFalse(grip.isHidden())
            self.assertEqual(grip.text(), "◢")
            self.assertEqual(grip.geometry().right(), window.width() - 5)
            self.assertEqual(grip.geometry().bottom(), window.height() - 5)

            grip._start_size = window.size()
            grip._start_global = QtCore.QPoint(100, 100)
            grip._resize_from_global(QtCore.QPoint(220, 180))
            self.assertEqual(window.size().width(), 640)
            self.assertEqual(window.size().height(), 380)
        finally:
            window.close()

    def test_manual_scroll_disables_tail_follow_until_user_returns_to_bottom(self):
        scrollbar = QScrollBar()
        scrollbar.setRange(0, 100)
        view = SimpleNamespace(
            _programmatic_scroll=False,
            _follow_scroll_tail=True,
            scroll_area=SimpleNamespace(verticalScrollBar=lambda: scrollbar),
        )

        OverlayWindow._on_scroll_position_changed(view, 30)
        self.assertFalse(view._follow_scroll_tail)
        scrollbar.setValue(30)
        OverlayWindow._scroll_to_bottom(view)
        self.assertEqual(scrollbar.value(), 30)

        OverlayWindow._on_scroll_position_changed(view, 100)
        self.assertTrue(view._follow_scroll_tail)
        OverlayWindow._scroll_to_bottom(view)
        self.assertEqual(scrollbar.value(), 100)

    def test_translation_renders_stable_prefix_and_mutable_tail_in_place(self):
        item = LogItem(3, "00:00:00", "source", "稳定前缀变化尾部")

        item.update_translated("稳定前缀变化尾部", 4)

        rendered = item.translated_label.text()
        self.assertIn('color:#ffffff', rendered)
        self.assertIn('color:#d7dbe5', rendered)
        self.assertIn("稳定前缀", rendered)
        self.assertEqual(item._committed_prefix_length, 4)

    def test_partial_record_does_not_shrink_until_final(self):
        item = LogItem(
            4,
            "00:00:00",
            "source",
            "这是会在窄玻璃字幕窗口内换成多行的临时翻译。" * 5,
        )
        item.resize(220, 400)
        item.refresh_layout()
        provisional_height = item.height()

        item.update_translated("短句", preserve_partial_height=True)
        item.refresh_layout(preserve_partial_height=True)
        self.assertEqual(item.height(), provisional_height)

        self.assertTrue(item.set_finalized(True))
        item.refresh_layout(preserve_partial_height=False)
        self.assertLess(item.height(), provisional_height)

    def test_current_partial_uses_a_trailing_growth_cushion(self):
        with patch("overlay_window.HAS_APPKIT", False):
            window = OverlayWindow(window_width=480, window_height=260)
        try:
            window.update_text(1, "source", "draft", "partial")
            self.assertEqual(
                window._growth_cushion.height(),
                GLASS_CURRENT_GROWTH_CUSHION,
            )
            self.assertEqual(
                window.container_layout.indexOf(window._growth_cushion),
                window.container_layout.count() - 1,
            )

            window.update_text(1, "source", "final", "final")
            self.assertEqual(window._growth_cushion.height(), 0)
        finally:
            window.close()

    def test_tail_anchor_waits_for_growth_cushion_before_scrolling(self):
        self.assertEqual(
            OverlayWindow._tail_scroll_target(40, 200, 180, 200),
            40,
        )
        self.assertEqual(
            OverlayWindow._tail_scroll_target(40, 200, 220, 200),
            40 + 32 + GLASS_TAIL_SCROLL_SLACK,
        )

    def test_visible_history_is_capped_without_deleting_transcript_records(self):
        class Widget:
            def __init__(self):
                self.deleted = False

            def deleteLater(self):
                self.deleted = True

        removed = []
        self.assertEqual(MAX_VISIBLE_TRANSCRIPT_ITEMS, 40)
        widgets = [Widget() for _ in range(MAX_VISIBLE_TRANSCRIPT_ITEMS + 5)]
        view = SimpleNamespace(
            items=list(enumerate(widgets)),
            transcript_data={
                index: {"original": str(index)}
                for index in range(MAX_VISIBLE_TRANSCRIPT_ITEMS + 5)
            },
            container_layout=SimpleNamespace(removeWidget=removed.append),
        )

        OverlayWindow._trim_visible_items(view)

        self.assertEqual(len(view.items), MAX_VISIBLE_TRANSCRIPT_ITEMS)
        self.assertEqual(
            [item[0] for item in view.items],
            list(range(5, MAX_VISIBLE_TRANSCRIPT_ITEMS + 5)),
        )
        self.assertEqual(removed, widgets[:5])
        self.assertTrue(all(widget.deleted for widget in widgets[:5]))
        self.assertEqual(
            len(view.transcript_data), MAX_VISIBLE_TRANSCRIPT_ITEMS + 5
        )

    def test_late_record_outside_visible_glass_projection_does_not_reappear(self):
        with patch("overlay_window.HAS_APPKIT", False):
            window = OverlayWindow(
                window_width=480,
                window_height=260,
                display_mode="glass",
            )
        try:
            for chunk_id in range(1, MAX_VISIBLE_TRANSCRIPT_ITEMS + 6):
                window.update_text(
                    chunk_id,
                    f"source {chunk_id}",
                    f"translation {chunk_id}",
                )

            window.update_text(1, "source 1", "late final", "final")

            self.assertEqual(
                [chunk_id for chunk_id, _widget in window.items],
                list(range(6, MAX_VISIBLE_TRANSCRIPT_ITEMS + 6)),
            )
            self.assertEqual(window.transcript_data[1]["translated"], "late final")
        finally:
            window.close()

    def test_glass_window_has_no_custom_cursor_or_qsizegrip_crash_path(self):
        with open(__import__("overlay_window").__file__, encoding="utf-8") as handle:
            source = handle.read()

        self.assertNotIn("setCursor(", source)
        self.assertNotIn("QSizeGrip", source)


if __name__ == "__main__":
    unittest.main()
