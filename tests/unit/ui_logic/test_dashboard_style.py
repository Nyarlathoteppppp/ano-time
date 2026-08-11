import unittest

from dashboard_support.style import STYLESHEET


class DashboardStyleTests(unittest.TestCase):
    def test_normal_and_fullscreen_dashboard_are_seventy_percent_transparent(self):
        self.assertEqual(
            STYLESHEET.count("background-color: rgba(255, 184, 211, 77);"),
            2,
        )
        self.assertNotIn("background-color: rgba(28, 30, 39, 252);", STYLESHEET)


if __name__ == "__main__":
    unittest.main()
