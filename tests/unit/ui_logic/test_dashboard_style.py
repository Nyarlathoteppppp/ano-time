import unittest

from dashboard_support.style import STYLESHEET


class DashboardStyleTests(unittest.TestCase):
    def test_dashboard_root_is_fully_opaque(self):
        self.assertIn("background-color: rgb(28, 30, 39);", STYLESHEET)
        self.assertNotIn("fullscreenFallback", STYLESHEET)


if __name__ == "__main__":
    unittest.main()
