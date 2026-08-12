import unittest
from unittest.mock import MagicMock, patch

from dashboard_support import native_window_appearance


class NativeWindowAppearanceTests(unittest.TestCase):
    def test_transparency_clears_native_backing(self):
        window = MagicMock()
        clear = object()
        color = MagicMock()
        color.clearColor.return_value = clear
        with (
            patch.object(native_window_appearance, "native_window", return_value=window),
            patch.object(native_window_appearance, "NSColor", color),
        ):
            self.assertTrue(
                native_window_appearance.apply_window_backing(object(), 30)
            )

        window.setOpaque_.assert_called_once_with(False)
        window.setBackgroundColor_.assert_called_once_with(clear)

    def test_zero_transparency_restores_opaque_backing(self):
        window = MagicMock()
        background = object()
        color = MagicMock()
        color.windowBackgroundColor.return_value = background
        with (
            patch.object(native_window_appearance, "native_window", return_value=window),
            patch.object(native_window_appearance, "NSColor", color),
        ):
            self.assertTrue(
                native_window_appearance.apply_window_backing(object(), 0)
            )

        window.setOpaque_.assert_called_once_with(True)
        window.setBackgroundColor_.assert_called_once_with(background)


if __name__ == "__main__":
    unittest.main()
