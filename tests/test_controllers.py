import unittest
from types import SimpleNamespace

from permission_controller import PermissionController
from session_controller import SessionController
from shortcut_controller import ShortcutController


class FakeWidget:
    def __init__(self):
        self.text = ""
        self.stylesheet = ""
        self.visible = True
        self.enabled = True

    def setText(self, text):
        self.text = text

    def setStyleSheet(self, stylesheet):
        self.stylesheet = stylesheet

    def setEnabled(self, enabled):
        self.enabled = enabled

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


class ControllerTests(unittest.TestCase):
    def test_running_start_only_reveals_existing_overlay(self):
        calls = []
        view = SimpleNamespace(
            _session_state="running",
            overlay_window=SimpleNamespace(show=lambda: calls.append("show")),
        )
        SessionController(view, lambda _generation: self.fail("worker created")).start()
        self.assertEqual(calls, ["show"])

    def test_stale_startup_result_is_disposed_without_creating_window(self):
        calls = []
        pipeline = SimpleNamespace(stop=lambda: calls.append("pipeline stopped"))
        view = SimpleNamespace(_session_generation=4, _session_state="idle")
        SessionController(view, None).pipeline_ready(3, pipeline)
        self.assertEqual(calls, ["pipeline stopped"])

    def test_session_stop_releases_pipeline_and_overlay(self):
        calls = []
        view = SimpleNamespace(
            _session_generation=3,
            _session_state="running",
            overlay_window=SimpleNamespace(close=lambda: calls.append("overlay")),
            pipeline=SimpleNamespace(stop=lambda: calls.append("pipeline")),
            status_label=FakeWidget(),
            stop_btn=FakeWidget(),
            start_btn=FakeWidget(),
            showNormal=lambda: calls.append("normal"),
        )
        SessionController(view, None).stop()
        self.assertEqual(view._session_state, "idle")
        self.assertIsNone(view.pipeline)
        self.assertIsNone(view.overlay_window)
        self.assertEqual(calls, ["overlay", "pipeline", "normal"])

    def test_shortcut_idle_launches_notch_through_existing_view_api(self):
        calls = []
        display_mode = SimpleNamespace(
            findData=lambda value: 2 if value == "notch" else -1,
            setCurrentIndex=lambda index: calls.append(("mode", index)),
        )
        view = SimpleNamespace(
            shortcut_enabled=True,
            _session_state="idle",
            display_mode=display_mode,
            status_label=FakeWidget(),
            on_start=lambda: calls.append("start"),
            pipeline=None,
        )
        controller = ShortcutController.__new__(ShortcutController)
        controller.view = view
        controller.activated()
        self.assertEqual(calls, [("mode", 2), "start"])

    def test_permission_result_restores_button_and_surfaces_silence(self):
        view = SimpleNamespace(
            test_system_audio_btn=FakeWidget(),
            audio_test_status=FakeWidget(),
        )
        controller = PermissionController(view, None)
        controller.on_system_audio_test_result(True, "", 0.0)
        self.assertTrue(view.test_system_audio_btn.enabled)
        self.assertIn("captured audio was silent", view.audio_test_status.text)


if __name__ == "__main__":
    unittest.main()
