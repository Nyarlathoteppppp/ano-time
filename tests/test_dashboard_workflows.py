import os
import configparser
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from dashboard import Dashboard
from dashboard import DEFAULT_AUDIO_SETTINGS
from dashboard import ModelListWorker
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
        self.assertGreaterEqual(self.dashboard.workflow_preview.minimumHeight(), 48)
        self.assertTrue(self.dashboard.workflow_preview.wordWrap())
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

    def test_restore_audio_defaults_changes_only_audio_controls(self):
        original_workflow = self.dashboard.translation_workflow.currentData()
        original_target = self.dashboard.target_lang.currentData()
        original_display = self.dashboard.display_mode.currentData()
        self.dashboard.sample_rate.setValue(48000)
        self.dashboard.silence_thresh.setValue(0.2)
        self.dashboard.silence_dur.setValue(1.7)
        self.dashboard.update_interval.setValue(1.5)
        system_index = self.dashboard.device_combo.findData("system")
        self.dashboard.device_combo.setCurrentIndex(system_index)

        self.dashboard.restore_audio_defaults()

        self.assertEqual(
            self.dashboard.device_combo.currentData(),
            DEFAULT_AUDIO_SETTINGS["device_index"],
        )
        self.assertEqual(
            self.dashboard.home_device_combo.currentData(),
            DEFAULT_AUDIO_SETTINGS["device_index"],
        )
        self.assertEqual(
            self.dashboard.sample_rate.value(),
            DEFAULT_AUDIO_SETTINGS["sample_rate"],
        )
        self.assertAlmostEqual(
            self.dashboard.silence_thresh.value(),
            DEFAULT_AUDIO_SETTINGS["silence_threshold"],
        )
        self.assertAlmostEqual(
            self.dashboard.silence_dur.value(),
            DEFAULT_AUDIO_SETTINGS["silence_duration"],
        )
        self.assertAlmostEqual(
            self.dashboard.update_interval.value(),
            DEFAULT_AUDIO_SETTINGS["update_interval"],
        )
        self.assertEqual(
            self.dashboard.translation_workflow.currentData(), original_workflow
        )
        self.assertEqual(self.dashboard.target_lang.currentData(), original_target)
        self.assertEqual(self.dashboard.display_mode.currentData(), original_display)
        self.assertIn("Click Save Settings", self.dashboard.audio_test_status.text())

    def test_running_setting_change_shows_restart_notice(self):
        self.dashboard._session_state = "running"
        self.dashboard.target_lang.setCurrentIndex(
            (self.dashboard.target_lang.currentIndex() + 1)
            % self.dashboard.target_lang.count()
        )

        self.assertFalse(self.dashboard.pending_settings_label.isHidden())
        self.assertIn(
            "Stop and Launch again",
            self.dashboard.pending_settings_label.text(),
        )

    def test_unchanged_secrets_are_not_rewritten_to_keychain(self):
        with tempfile.TemporaryDirectory() as directory:
            fake_module = os.path.join(directory, "dashboard.py")
            with (
                patch.object(dashboard_module, "__file__", fake_module),
                patch.object(dashboard_module.config, "reload"),
                patch.object(
                    keychain_store,
                    "store_for_config",
                    side_effect=lambda account, value: f"keychain://test/{account}",
                ) as store_secret,
            ):
                self.dashboard.save_config(show_status=False)

        store_secret.assert_not_called()

    def test_only_edited_secret_is_rewritten_to_keychain(self):
        self.dashboard.groq_api_key.setText(
            self.dashboard.groq_api_key.text() + "-edited"
        )
        with tempfile.TemporaryDirectory() as directory:
            fake_module = os.path.join(directory, "dashboard.py")
            with (
                patch.object(dashboard_module, "__file__", fake_module),
                patch.object(dashboard_module.config, "reload"),
                patch.object(
                    keychain_store,
                    "store_for_config",
                    side_effect=lambda account, value: f"keychain://test/{account}",
                ) as store_secret,
            ):
                self.dashboard.save_config(show_status=False)

        self.assertEqual(store_secret.call_count, 1)
        self.assertEqual(store_secret.call_args.args[0], "providers.groq")

    def test_model_list_worker_uses_verified_bounded_http_client(self):
        response = SimpleNamespace(
            data=[SimpleNamespace(id="model-b"), SimpleNamespace(id="model-a")]
        )
        client = MagicMock()
        client.models.list.return_value = response
        http_client = MagicMock()
        http_client.__enter__.return_value = http_client
        loaded = []
        failed = []
        worker = ModelListWorker("secret", "https://example.test/v1")
        worker.loaded.connect(loaded.append)
        worker.failed.connect(failed.append)

        with (
            patch("httpx.Client", return_value=http_client) as client_factory,
            patch("openai.OpenAI", return_value=client) as openai_factory,
        ):
            worker.run()

        self.assertEqual(loaded, [["model-b", "model-a"]])
        self.assertEqual(failed, [])
        self.assertTrue(client_factory.call_args.kwargs["verify"])
        self.assertEqual(openai_factory.call_args.kwargs["max_retries"], 0)


if __name__ == "__main__":
    unittest.main()
