import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.qt import QtWidgets


QApplication = QtWidgets.QApplication

from dashboard_support.panels import AsrPanel


def settings(**overrides):
    values = {
        "asr_backend": "apple",
        "whisper_model": "medium",
        "funasr_model": "iic/SenseVoiceSmall",
        "whisper_device": "auto",
        "whisper_compute_type": "float16",
        "source_language": "en",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class AsrPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_apple_backend_hides_unused_model_controls(self):
        panel = AsrPanel(settings())
        self.addCleanup(panel.close)

        self.assertTrue(panel.whisper_model.isHidden())
        self.assertTrue(panel.funasr_model.isHidden())
        self.assertTrue(panel.device_type.isHidden())
        self.assertTrue(panel.compute_type.isHidden())
        self.assertFalse(panel.source_language.isHidden())
        self.assertIn("Apple 原生实时识别", panel.backend_hint.text())

    def test_parakeet_eou_is_explicit_experimental_streaming_choice(self):
        panel = AsrPanel(settings())
        self.addCleanup(panel.close)

        panel.asr_backend.setCurrentText("parakeet_eou")

        self.assertTrue(panel.whisper_model.isHidden())
        self.assertTrue(panel.device_type.isHidden())
        self.assertFalse(panel.source_language.isEnabled())
        self.assertEqual(panel.source_language.currentData(), "en")
        self.assertIn("实验", panel.backend_hint.text())

    def test_only_installed_user_ready_asr_backends_are_selectable(self):
        panel = AsrPanel(settings())
        self.addCleanup(panel.close)

        choices = [panel.asr_backend.itemText(index) for index in range(panel.asr_backend.count())]

        self.assertEqual(choices, ["apple", "parakeet_eou", "mlx"])
        self.assertNotIn("whisper", choices)
        self.assertNotIn("funasr", choices)

    def test_unavailable_legacy_backend_configuration_falls_back_to_apple_in_the_ui(self):
        legacy_settings = settings()
        legacy_settings.asr_backend = "funasr"

        panel = AsrPanel(legacy_settings)
        self.addCleanup(panel.close)

        self.assertEqual(panel.asr_backend.currentText(), "apple")


if __name__ == "__main__":
    unittest.main()
