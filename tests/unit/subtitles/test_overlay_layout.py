import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from overlay_window import LogItem


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


if __name__ == "__main__":
    unittest.main()
