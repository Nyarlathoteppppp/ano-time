import unittest

from dashboard import Dashboard


class FakeBlurWindow:
    def __init__(self):
        self.frame_updates = 0
        self.order_outs = 0

    def setFrame_display_(self, _frame, _display):
        self.frame_updates += 1

    def orderOut_(self, _sender):
        self.order_outs += 1


class FakeNativeWindow:
    def __init__(self):
        self.children = []
        self.additions = 0
        self.removals = 0

    def frame(self):
        return "frame"

    def childWindows(self):
        return list(self.children)

    def addChildWindow_ordered_(self, child, _order):
        self.children.append(child)
        self.additions += 1

    def removeChildWindow_(self, child):
        self.children.remove(child)
        self.removals += 1


class GlassLifecycleHarness:
    _sync_native_glass = Dashboard._sync_native_glass
    _detach_native_glass = Dashboard._detach_native_glass

    def __init__(self):
        self._native_blur_window = FakeBlurWindow()
        self.native = FakeNativeWindow()
        self.visible = True
        self.minimized = False
        self.fullscreen = False

    def _native_window(self):
        return self.native

    def isVisible(self):
        return self.visible

    def isMinimized(self):
        return self.minimized

    def isFullScreen(self):
        return self.fullscreen


class DashboardGlassLifecycleTests(unittest.TestCase):
    def test_visible_glass_attaches_as_child_without_independent_ordering(self):
        view = GlassLifecycleHarness()
        view._sync_native_glass()
        self.assertEqual(view.native.children, [view._native_blur_window])
        self.assertEqual(view.native.additions, 1)
        self.assertEqual(view._native_blur_window.frame_updates, 1)

        view._sync_native_glass()
        self.assertEqual(view.native.additions, 1)

    def test_minimized_glass_is_detached_and_ordered_out(self):
        view = GlassLifecycleHarness()
        view._sync_native_glass()
        view.minimized = True
        view._sync_native_glass()
        self.assertEqual(view.native.children, [])
        self.assertEqual(view.native.removals, 1)
        self.assertEqual(view._native_blur_window.order_outs, 1)

    def test_fullscreen_glass_is_detached_and_never_covers_qt_content(self):
        view = GlassLifecycleHarness()
        view._sync_native_glass()
        view.fullscreen = True

        view._sync_native_glass()

        self.assertEqual(view.native.children, [])
        self.assertEqual(view.native.removals, 1)
        self.assertEqual(view._native_blur_window.order_outs, 1)


if __name__ == "__main__":
    unittest.main()
