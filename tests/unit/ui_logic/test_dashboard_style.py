import unittest

from dashboard_support.style import STYLESHEET, dashboard_stylesheet


class DashboardStyleTests(unittest.TestCase):
    def test_dashboard_root_is_fully_opaque(self):
        self.assertIn("background-color: rgb(28, 30, 39);", STYLESHEET)
        self.assertNotIn("fullscreenFallback", STYLESHEET)

    def test_translucent_dashboard_uses_explicit_paint_layer(self):
        translucent = dashboard_stylesheet(30)
        self.assertIn("QWidget#DashboardRoot", translucent)
        self.assertIn("background: transparent;", translucent)
        self.assertNotIn("background-color: rgb(28, 30, 39);", translucent)

    def test_zero_transparency_keeps_opaque_style(self):
        self.assertEqual(dashboard_stylesheet(0), STYLESHEET)


if __name__ == "__main__":
    unittest.main()
