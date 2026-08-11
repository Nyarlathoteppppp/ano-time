import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QScrollBar

from overlay_window import (
    MAX_VISIBLE_TRANSCRIPT_ITEMS,
    LogItem,
    OverlayWindow,
)


class OverlayLayoutTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
