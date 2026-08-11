import unittest

from dashboard import Dashboard


class FakeTimer:
    def __init__(self):
        self.active = True
        self.starts = 0
        self.stops = 0

    def isActive(self):
        return self.active

    def start(self):
        self.active = True
        self.starts += 1

    def stop(self):
        self.active = False
        self.stops += 1


class TimerLifecycleHarness:
    _set_ui_timers_active = Dashboard._set_ui_timers_active

    def __init__(self):
        self.usage_timer = FakeTimer()
        self.refreshes = 0

    def _refresh_usage_status(self):
        self.refreshes += 1


class DashboardTimerLifecycleTests(unittest.TestCase):
    def test_hidden_dashboard_stops_and_restored_dashboard_refreshes_ui_timer(self):
        view = TimerLifecycleHarness()

        view._set_ui_timers_active(False)
        self.assertFalse(view.usage_timer.isActive())
        self.assertEqual(view.usage_timer.stops, 1)

        view._set_ui_timers_active(True)
        self.assertTrue(view.usage_timer.isActive())
        self.assertEqual(view.usage_timer.starts, 1)
        self.assertEqual(view.refreshes, 1)


if __name__ == "__main__":
    unittest.main()
