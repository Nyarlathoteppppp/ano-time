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

    def test_whisper_backend_exposes_only_consumed_controls(self):
        panel = AsrPanel(settings())
        self.addCleanup(panel.close)

        panel.asr_backend.setCurrentText("whisper")

        self.assertFalse(panel.whisper_model.isHidden())
        self.assertTrue(panel.funasr_model.isHidden())
        self.assertFalse(panel.device_type.isHidden())
        self.assertFalse(panel.compute_type.isHidden())

    def test_funasr_mps_enforces_float32_inside_panel(self):
        panel = AsrPanel(settings())
        self.addCleanup(panel.close)
        panel.show_mps_float32_warning = Mock()
        panel.compute_type.setCurrentText("int8")
        panel.device_type.setCurrentText("mps")

        panel.asr_backend.setCurrentText("funasr")

        self.assertEqual(panel.compute_type.currentText(), "float32")
        panel.show_mps_float32_warning.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
