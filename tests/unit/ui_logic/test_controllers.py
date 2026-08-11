import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_save_failure_rolls_starting_state_back_to_idle(self):
        view = SimpleNamespace(
            _session_generation=0,
            _session_state="idle",
            overlay_window=None,
            save_config=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("Keychain unavailable")
            ),
            status_label=FakeWidget(),
            start_btn=FakeWidget(),
        )

        SessionController(view, lambda _generation: self.fail("worker created")).start()

        self.assertEqual(view._session_state, "idle")
        self.assertTrue(view.start_btn.enabled)
        self.assertEqual(view.start_btn.text, "▶ Launch Translator")
        self.assertIn("Keychain unavailable", view.status_label.text)

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
            pause_btn=FakeWidget(),
            start_btn=FakeWidget(),
            showNormal=lambda: calls.append("normal"),
        )
        SessionController(view, None).stop()
        self.assertEqual(view._session_state, "idle")
        self.assertIsNone(view.pipeline)
        self.assertIsNone(view.overlay_window)
        self.assertFalse(view.pause_btn.visible)
        self.assertEqual(calls, ["overlay", "pipeline", "normal"])

    def test_session_stop_flushes_automatic_transcript(self):
        calls = []
        view = SimpleNamespace(
            _session_generation=3,
            _session_state="running",
            overlay_window=None,
            pipeline=None,
            transcript_recorder=SimpleNamespace(
                stop=lambda: calls.append("transcript")
            ),
            status_label=FakeWidget(),
            stop_btn=FakeWidget(),
            pause_btn=FakeWidget(),
            start_btn=FakeWidget(),
            showNormal=lambda: None,
        )
        SessionController(view, None).stop()
        self.assertEqual(calls, ["transcript"])
        self.assertIsNone(view.transcript_recorder)

    def test_pause_button_tracks_pipeline_state(self):
        paused = []
        view = SimpleNamespace(
            pipeline=SimpleNamespace(set_paused=paused.append),
            overlay_window=None,
            status_label=FakeWidget(),
            pause_btn=FakeWidget(),
        )
        controller = SessionController(view, None)
        controller.set_paused(True)
        self.assertEqual(paused, [True])
        self.assertEqual(view.pause_btn.text, "▶ Resume Translator")
        controller.set_paused(False)
        self.assertEqual(paused, [True, False])
        self.assertEqual(view.pause_btn.text, "⏸ Pause Translator")

    def test_usage_projection_starts_only_on_real_asr_activity(self):
        updates = []
        view = SimpleNamespace(
            _session_state="running",
            pipeline=SimpleNamespace(is_paused=False),
            update_runtime_status=lambda *args: updates.append(args)
        )
        controller = SessionController(view, None)
        with patch("session_controller.session_usage_meter.set_active") as set_active:
            controller.handle_runtime_status("Remote", "active", "Gemini")
            set_active.assert_not_called()
            controller.handle_runtime_status("ASR", "active", "Apple · listening")
            set_active.assert_called_once_with(True)
        self.assertEqual(len(updates), 2)

    def test_late_asr_status_cannot_restart_usage_clock_after_pause_or_stop(self):
        updates = []
        view = SimpleNamespace(
            _session_state="running",
            pipeline=SimpleNamespace(is_paused=True),
            update_runtime_status=lambda *args: updates.append(args),
        )
        controller = SessionController(view, None)
        with patch("session_controller.session_usage_meter.set_active") as set_active:
            controller.handle_runtime_status("ASR", "active", "late callback")
            view.pipeline.is_paused = False
            view._session_state = "idle"
            controller.handle_runtime_status("ASR", "active", "after stop")
            set_active.assert_not_called()
        self.assertEqual(len(updates), 2)

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
