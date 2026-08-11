import unittest
from unittest.mock import MagicMock, patch

from dashboard_support.native_transparency import apply_native_transparency


class NativeTransparencyTests(unittest.TestCase):
    def test_clears_existing_native_window_without_creating_child_windows(self):
        widget = object()
        window = MagicMock()

        with patch(
            "dashboard_support.native_transparency.native_window",
            return_value=window,
        ):
            self.assertTrue(apply_native_transparency(widget))

        window.setOpaque_.assert_called_once_with(False)
        window.setBackgroundColor_.assert_called_once()
        window.setTitlebarAppearsTransparent_.assert_called_once_with(False)
        window.addChildWindow_ordered_.assert_not_called()

    def test_unavailable_native_window_is_a_safe_noop(self):
        with patch(
            "dashboard_support.native_transparency.native_window",
            return_value=None,
        ):
            self.assertFalse(apply_native_transparency(object()))


if __name__ == "__main__":
    unittest.main()
