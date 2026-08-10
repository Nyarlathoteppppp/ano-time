import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from dashboard_support.panels import AudioPanel, DEFAULT_AUDIO_SETTINGS


def make_panel():
    callbacks = {
        "on_device_changed": Mock(),
        "on_refresh": Mock(),
        "on_use_system_audio": Mock(),
        "on_test_system_audio": Mock(),
        "on_open_permissions": Mock(),
        "on_restore_defaults": Mock(),
    }
    panel = AudioPanel(
        SimpleNamespace(
            sample_rate=48000,
            silence_threshold=0.2,
            silence_duration=1.7,
            update_interval=1.5,
        ),
        **callbacks,
    )
    return panel, callbacks


class AudioPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_panel_owns_audio_controls_and_initial_values(self):
        panel, _callbacks = make_panel()
        self.addCleanup(panel.close)

        self.assertEqual(panel.sample_rate.value(), 48000)
        self.assertAlmostEqual(panel.silence_thresh.value(), 0.2)
        self.assertAlmostEqual(panel.silence_dur.value(), 1.7)
        self.assertAlmostEqual(panel.update_interval.value(), 1.5)

    def test_restore_defaults_changes_only_panel_audio_values(self):
        panel, _callbacks = make_panel()
        self.addCleanup(panel.close)
        panel.device_combo.addItem("Auto (Default)", "auto")
        panel.device_combo.addItem("System Audio", "system")
        panel.device_combo.setCurrentIndex(1)

        panel.restore_defaults()

        self.assertEqual(panel.device_combo.currentData(), "auto")
        self.assertEqual(
            panel.sample_rate.value(), DEFAULT_AUDIO_SETTINGS["sample_rate"]
        )
        self.assertAlmostEqual(
            panel.update_interval.value(), DEFAULT_AUDIO_SETTINGS["update_interval"]
        )
        self.assertIn("Click Save Settings", panel.audio_test_status.text())

    def test_action_buttons_delegate_to_host_callbacks(self):
        panel, callbacks = make_panel()
        self.addCleanup(panel.close)

        panel.use_system_audio_btn.click()
        panel.test_system_audio_btn.click()
        panel.open_audio_permission_btn.click()
        panel.restore_audio_defaults_btn.click()

        callbacks["on_use_system_audio"].assert_called_once()
        callbacks["on_test_system_audio"].assert_called_once()
        callbacks["on_open_permissions"].assert_called_once()
        callbacks["on_restore_defaults"].assert_called_once()

    def test_controls_have_non_compressible_readable_heights(self):
        panel, _callbacks = make_panel()
        self.addCleanup(panel.close)
        for control in (
            panel.device_combo,
            panel.sample_rate,
            panel.silence_thresh,
            panel.silence_dur,
            panel.update_interval,
        ):
            self.assertGreaterEqual(control.minimumHeight(), 38)
        for button in (
            panel.use_system_audio_btn,
            panel.test_system_audio_btn,
            panel.open_audio_permission_btn,
            panel.restore_audio_defaults_btn,
        ):
            self.assertGreaterEqual(button.minimumHeight(), 42)


if __name__ == "__main__":
    unittest.main()
