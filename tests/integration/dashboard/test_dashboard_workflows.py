import os
import configparser
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel

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

    def test_dashboard_tabs_use_large_ano_icons_without_shortening_labels(self):
        self.assertEqual(self.dashboard.tabs.iconSize().width(), 48)
        self.assertEqual(
            [
                self.dashboard.tabs.tabText(index)
                for index in range(self.dashboard.tabs.count())
            ],
            ["Home", "Audio", "ASR · 语音识别", "AI · 翻译"],
        )
        self.assertTrue(
            all(
                not self.dashboard.tabs.tabIcon(index).isNull()
                for index in range(self.dashboard.tabs.count())
            )
        )

    def test_asr_panel_keeps_legacy_dashboard_control_aliases(self):
        self.assertIs(self.dashboard.asr_backend, self.dashboard.asr_panel.asr_backend)
        self.assertIs(
            self.dashboard.whisper_model, self.dashboard.asr_panel.whisper_model
        )
        self.assertIs(
            self.dashboard.source_language, self.dashboard.asr_panel.source_language
        )

    def test_audio_panel_keeps_legacy_dashboard_control_aliases(self):
        self.assertIs(
            self.dashboard.device_combo, self.dashboard.audio_panel.device_combo
        )
        self.assertIs(self.dashboard.sample_rate, self.dashboard.audio_panel.sample_rate)
        self.assertIs(
            self.dashboard.audio_test_status,
            self.dashboard.audio_panel.audio_test_status,
        )
        self.assertIs(self.dashboard.audio_scroll.widget(), self.dashboard.audio_panel)
        self.assertTrue(self.dashboard.audio_scroll.widgetResizable())

    def test_user_titlebar_close_requests_full_quit(self):
        spontaneous = MagicMock()
        spontaneous.spontaneous.return_value = True
        programmatic = MagicMock()
        programmatic.spontaneous.return_value = False

        self.dashboard._force_quit = False
        self.assertTrue(self.dashboard._should_quit_for_close_event(spontaneous))
        self.assertFalse(self.dashboard._should_quit_for_close_event(programmatic))

        self.dashboard._force_quit = True
        self.assertTrue(self.dashboard._should_quit_for_close_event(programmatic))
        self.dashboard._force_quit = False

    def test_home_explains_notch_size_cycle(self):
        text = self.dashboard.notch_help.text()
        self.assertIn("小 → 中 → 大", text)
        self.assertIn("1 条", text)
        self.assertIn("2 条", text)
        self.assertIn("3 条", text)

    def test_existing_install_opens_on_frozen_smart_hybrid_chain(self):
        self.assertEqual(
            self.dashboard.translation_workflow.currentData(), "smart_hybrid"
        )
        self.assertEqual(self.dashboard.bridge_provider.currentData(), "groq")
        self.assertIn("GLM Free", self.dashboard.workflow_preview.text())
        self.assertIn("Gemini Paid", self.dashboard.workflow_preview.text())
        self.assertGreaterEqual(self.dashboard.workflow_preview.minimumHeight(), 48)
        self.assertTrue(self.dashboard.workflow_preview.wordWrap())
        self.assertTrue(self.dashboard.provider.isHidden())
        self.assertFalse(self.dashboard.gemini_api_key.isHidden())
        self.assertEqual(
            [
                self.dashboard.api_test_provider.itemData(index)
                for index in range(self.dashboard.api_test_provider.count())
            ],
            ["groq", "cerebras", "gemini", "glm"],
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
        self.assertIn(
            "当前最终模型", self.dashboard.api_test_provider.itemText(0)
        )
        self.assertIn(
            "cerebras",
            [
                self.dashboard.api_test_provider.itemData(index)
                for index in range(self.dashboard.api_test_provider.count())
            ],
        )

    def test_switching_from_hybrid_resets_speed_test_to_single_final_model(self):
        self._choose_workflow("smart_hybrid")
        groq_index = self.dashboard.api_test_provider.findData("groq")
        self.dashboard.api_test_provider.setCurrentIndex(groq_index)
        self._choose_workflow("single_model")
        self.assertEqual(self.dashboard.api_test_provider.currentData(), "single")

    def test_single_model_credentials_are_grouped_in_visual_order(self):
        layout = self.dashboard.translation_layout
        row = lambda widget: layout.getWidgetPosition(widget)[0]
        bridge_row = lambda widget: self.dashboard.bridge_layout.getWidgetPosition(widget)[0]
        self.assertLess(bridge_row(self.dashboard.bridge_provider), bridge_row(self.dashboard.groq_api_key))
        self.assertLess(
            bridge_row(self.dashboard.groq_api_key),
            bridge_row(self.dashboard.cerebras_api_key),
        )
        self.assertLess(row(self.dashboard.bridge_card), row(self.dashboard.provider))
        self.assertLess(row(self.dashboard.provider), row(self.dashboard.api_key))
        self.assertLess(row(self.dashboard.api_key), row(self.dashboard.base_url))
        self.assertLess(row(self.dashboard.base_url), row(self.dashboard.model_container))
        self.assertLess(row(self.dashboard.model_container), row(self.dashboard.gemini_api_key))

    def test_bridge_card_explains_optional_non_blocking_behavior(self):
        labels = " ".join(
            label.text() for label in self.dashboard.bridge_card.findChildren(QLabel)
        )
        self.assertIn("可选", labels)
        self.assertIn("不会阻塞", labels)
        self.dashboard.bridge_provider.setCurrentIndex(
            self.dashboard.bridge_provider.findData("off")
        )
        self.assertTrue(self.dashboard.groq_api_key.isHidden())
        self.assertTrue(self.dashboard.cerebras_api_key.isHidden())

    def test_bridge_toggle_and_provider_selector_stay_in_sync(self):
        self.dashboard.bridge_toggle.click()
        self.assertEqual(self.dashboard.bridge_provider.currentData(), "off")
        self.assertEqual(self.dashboard.bridge_toggle.text(), "Bridge OFF")
        self.assertFalse(self.dashboard.bridge_toggle.isChecked())

        self.dashboard.bridge_toggle.click()
        self.assertEqual(self.dashboard.bridge_provider.currentData(), "groq")
        self.assertEqual(self.dashboard.bridge_toggle.text(), "Bridge ON")
        self.assertTrue(self.dashboard.bridge_toggle.isChecked())

    def test_save_shows_global_success_feedback(self):
        with (
            patch.object(
                dashboard_module.DashboardSettingsRepository,
                "save",
                return_value={},
            ),
            patch.object(
                dashboard_module.ProviderProfileRepository,
                "save",
            ),
            patch.object(dashboard_module.config, "reload"),
        ):
            self.assertTrue(self.dashboard.save_config())

        self.assertFalse(self.dashboard.save_feedback_label.isHidden())
        self.assertIn("Saved", self.dashboard.save_feedback_label.text())
        self.assertEqual(self.dashboard.save_btn.text(), "✓ Saved")

    def test_save_failure_is_visible_and_returns_false(self):
        with patch.object(
            dashboard_module.DashboardSettingsRepository,
            "save",
            side_effect=OSError("read-only config"),
        ):
            self.assertFalse(self.dashboard.save_config())

        self.assertFalse(self.dashboard.save_feedback_label.isHidden())
        self.assertIn("read-only config", self.dashboard.save_feedback_label.text())
        self.assertEqual(self.dashboard.save_btn.text(), "Save Failed")

    def test_workflow_labels_separate_regular_users_from_developer_chain(self):
        labels = {
            self.dashboard.translation_workflow.itemData(index):
            self.dashboard.translation_workflow.itemText(index)
            for index in range(self.dashboard.translation_workflow.count())
        }
        self.assertIn("普通用户", labels["single_model"])
        self.assertIn("开发者专用", labels["smart_hybrid"])
        self.assertIn("无需 API", labels["apple_only"])

    def test_workflow_preview_explains_portability_and_failure_behavior(self):
        self._choose_workflow("smart_hybrid")
        self.assertIn("目前不通用", self.dashboard.workflow_preview.text())
        self._choose_workflow("single_model")
        preview = self.dashboard.workflow_preview.text()
        self.assertIn("通用流程", preview)
        self.assertIn("保留 Apple 草稿", preview)

    def test_single_model_offers_popular_and_custom_openai_compatible_providers(self):
        providers = [
            self.dashboard.provider.itemText(index)
            for index in range(self.dashboard.provider.count())
        ]
        self.assertIn("OpenAI", providers)
        self.assertIn("Google Gemini", providers)
        self.assertIn("Groq", providers)
        self.assertIn("OpenRouter", providers)
        self.assertIn("Custom OpenAI-Compatible", providers)

    def test_provider_presets_do_not_prevent_custom_model_ids(self):
        self._choose_workflow("single_model")
        self.dashboard.provider.setCurrentText("OpenAI")
        self.assertIn("gpt-5-mini", [
            self.dashboard.model.itemText(index)
            for index in range(self.dashboard.model.count())
        ])
        self.dashboard.model.setCurrentText("vendor/custom-course-model")
        self.assertEqual(
            self.dashboard.model.currentText(), "vendor/custom-course-model"
        )

    def test_custom_model_selection_survives_provider_switching(self):
        self._choose_workflow("single_model")
        self.dashboard.provider.setCurrentText("OpenAI")
        self.dashboard.model.setCurrentText("vendor/custom-course-model")
        self.dashboard.provider.setCurrentText("Groq")
        self.dashboard.provider.setCurrentText("OpenAI")
        self.assertEqual(
            self.dashboard.model.currentText(), "vendor/custom-course-model"
        )

    def test_provider_profile_snapshot_only_contains_active_single_model(self):
        self._choose_workflow("single_model")
        self.dashboard.provider.setCurrentText("OpenAI")
        self.dashboard.api_key.setText("profile-key")
        self.dashboard.model.setCurrentText("vendor/custom-course-model")
        profiles = self.dashboard._provider_profile_snapshot()
        self.assertEqual(list(profiles), ["OpenAI"])
        self.assertEqual(profiles["OpenAI"]["api_key"], "profile-key")
        self.assertEqual(
            profiles["OpenAI"]["selected_model"], "vendor/custom-course-model"
        )

    def test_smart_hybrid_save_does_not_touch_single_model_profiles(self):
        self._choose_workflow("smart_hybrid")
        self.assertEqual(self.dashboard._provider_profile_snapshot(), {})

    def test_pages_explain_when_settings_take_effect(self):
        self.assertIn("重新 Launch", self.dashboard.apply_hint.text())
        self.assertIn("重新 Launch", self.dashboard.audio_panel.apply_hint.text())
        self.assertIn("重新 Launch", self.dashboard.asr_panel.apply_hint.text())

    def test_current_lecture_topic_starts_blank_for_each_app_session(self):
        self.assertEqual(self.dashboard.current_course_topic.text(), "")
        self.assertIn("session only", self.dashboard.current_course_topic.toolTip())

    def test_apple_only_hides_remote_credentials_and_forces_local_draft(self):
        self._choose_workflow("apple_only")
        self.assertTrue(self.dashboard.provider.isHidden())
        self.assertTrue(self.dashboard.groq_api_key.isHidden())
        self.assertTrue(self.dashboard.cerebras_api_key.isHidden())
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
