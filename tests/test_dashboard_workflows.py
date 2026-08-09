import os
import configparser
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from dashboard import Dashboard
import dashboard as dashboard_module
from keychain_store import store as keychain_store
from shortcut_controller import ShortcutController


class DashboardWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patcher = patch.object(ShortcutController, "start", lambda _self: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dashboard = Dashboard()
        self.addCleanup(self.dashboard.close)

    def _choose_workflow(self, value):
        self.dashboard.translation_workflow.setCurrentIndex(
            self.dashboard.translation_workflow.findData(value)
        )

    def test_existing_install_opens_on_frozen_smart_hybrid_chain(self):
        self.assertEqual(
            self.dashboard.translation_workflow.currentData(), "smart_hybrid"
        )
        self.assertEqual(self.dashboard.bridge_provider.currentData(), "groq")
        self.assertIn("Gemini/GLM", self.dashboard.workflow_preview.text())
        self.assertTrue(self.dashboard.provider.isHidden())
        self.assertFalse(self.dashboard.gemini_api_key.isHidden())
        self.assertEqual(
            [
                self.dashboard.api_test_provider.itemData(index)
                for index in range(self.dashboard.api_test_provider.count())
            ],
            ["groq", "gemini", "glm", "qwen"],
        )

    def test_single_model_exposes_provider_and_optional_bridge(self):
        self._choose_workflow("single_model")
        self.assertFalse(self.dashboard.provider.isHidden())
        self.assertTrue(self.dashboard.gemini_api_key.isHidden())
        self.assertIn(
            self.dashboard.provider.currentText(), self.dashboard.workflow_preview.text()
        )
        self.assertEqual(
            self.dashboard.api_test_provider.itemData(0), "single"
        )

    def test_apple_only_hides_remote_credentials_and_forces_local_draft(self):
        self._choose_workflow("apple_only")
        self.assertTrue(self.dashboard.provider.isHidden())
        self.assertTrue(self.dashboard.groq_api_key.isHidden())
        self.assertTrue(self.dashboard.gemini_api_key.isHidden())
        self.assertEqual(self.dashboard.fast_translation_backend.currentText(), "apple")
        self.assertIn("完全本地", self.dashboard.workflow_preview.text())
        self.assertTrue(self.dashboard.api_test_btn.isHidden())

    def test_save_persists_workflow_bridge_and_single_provider_separately(self):
        self._choose_workflow("single_model")
        self.dashboard.bridge_provider.setCurrentIndex(
            self.dashboard.bridge_provider.findData("off")
        )
        self.dashboard.provider.setCurrentText("Alibaba Cloud Qwen-MT")
        with tempfile.TemporaryDirectory() as directory:
            fake_module = os.path.join(directory, "dashboard.py")
            with (
                patch.object(dashboard_module, "__file__", fake_module),
                patch.object(dashboard_module.config, "reload"),
                patch.object(
                    keychain_store,
                    "store_for_config",
                    side_effect=lambda account, value: (
                        f"keychain://test/{account}" if value else ""
                    ),
                ),
            ):
                self.dashboard.save_config(show_status=False)
            saved = configparser.ConfigParser()
            saved.read(os.path.join(directory, "config.ini"))

        self.assertEqual(saved.get("translation", "workflow"), "single_model")
        self.assertEqual(saved.get("translation", "bridge_provider"), "off")
        self.assertEqual(
            saved.get("translation", "single_provider"),
            "Alibaba Cloud Qwen-MT",
        )


if __name__ == "__main__":
    unittest.main()
