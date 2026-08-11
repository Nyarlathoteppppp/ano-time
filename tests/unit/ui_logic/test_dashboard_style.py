import unittest

from dashboard_support.style import DASHBOARD_BACKGROUND_RGBA, STYLESHEET


class DashboardStyleTests(unittest.TestCase):
    def test_normal_and_fullscreen_dashboard_are_fifteen_percent_transparent(self):
        self.assertEqual(DASHBOARD_BACKGROUND_RGBA, (28, 30, 39, 217))
        self.assertGreaterEqual(STYLESHEET.count("background: transparent;"), 3)
        self.assertNotIn("background-color: rgba(28, 30, 39, 252);", STYLESHEET)


if __name__ == "__main__":
    unittest.main()
