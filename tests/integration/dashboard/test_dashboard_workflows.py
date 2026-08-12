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
from dashboard_support.workers import SmartHintTestWorker
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
        bridge_default = patch.object(dashboard_module.config, "bridge_provider", "off")
        bridge_default.start()
        self.addCleanup(bridge_default.stop)
        pacing_default = patch.object(
            dashboard_module.config, "subtitle_update_pacing", "fluent"
        )
        pacing_default.start()
        self.addCleanup(pacing_default.stop)
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

    def test_home_exposes_display_stability_and_update_pacing_preferences(self):
        self.assertEqual(
            self.dashboard.subtitle_presentation_policy.currentData(), "realtime"
        )
        self.assertEqual(
            self.dashboard.subtitle_update_pacing.currentData(), "fluent"
        )
        self.dashboard.subtitle_presentation_policy.setCurrentIndex(
            self.dashboard.subtitle_presentation_policy.findData("stable")
        )
        self.dashboard.subtitle_update_pacing.setCurrentIndex(
            self.dashboard.subtitle_update_pacing.findData("focus")
        )
        snapshot = self.dashboard.collect_settings()
        self.assertEqual(snapshot.subtitle_presentation_policy, "stable")
        self.assertEqual(snapshot.subtitle_update_pacing, "focus")

    def test_home_shows_permanent_transcript_status_and_output_location(self):
        self.assertIn("永久保留", self.dashboard.transcript_recording_checkbox.text())
        self.dashboard.set_transcript_recording_status(
            "recording", "/Users/test/Documents/Anotime Records/lecture.txt"
        )
        status = self.dashboard.transcript_status_label.text()
        self.assertIn("Recording", status)
        self.assertIn("lecture.txt", status)
        self.assertEqual(
            self.dashboard.transcript_output_directory(),
            os.path.expanduser("~/Documents/Anotime Records"),
        )

    def test_existing_install_opens_on_frozen_smart_hybrid_chain(self):
        self.assertEqual(
            self.dashboard.translation_workflow.currentData(), "smart_hybrid"
        )
        self.assertEqual(self.dashboard.bridge_provider.currentData(), "off")
        self.assertIn("主翻译：", self.dashboard.workflow_preview.text())
        self.assertIn("GLM 接管", self.dashboard.workflow_preview.text())
        self.assertGreaterEqual(self.dashboard.workflow_preview.minimumHeight(), 48)
        self.assertTrue(self.dashboard.workflow_preview.wordWrap())
        self.assertTrue(self.dashboard.provider.isHidden())
        self.assertFalse(self.dashboard.smart_hybrid_final_provider.isHidden())
        self.assertIn(
            self.dashboard.smart_hybrid_final_provider.currentData(),
            {"gemini", "groq_cerebras"},
        )
        uses_groq_cerebras = (
            self.dashboard.smart_hybrid_final_provider.currentData()
            == "groq_cerebras"
        )
        self.assertEqual(self.dashboard.gemini_api_key.isHidden(), uses_groq_cerebras)
        targets = [
            self.dashboard.api_test_provider.itemData(index)
            for index in range(self.dashboard.api_test_provider.count())
        ]
        self.assertIn("glm", targets)
        self.assertTrue(
            {"gemini"}.issubset(targets)
            or {"groq", "cerebras"}.issubset(targets)
        )

    def test_hybrid_final_selector_exposes_combined_groq_cerebras_pool(self):
        self._choose_workflow("smart_hybrid")
        self.dashboard.smart_hybrid_final_provider.setCurrentIndex(
            self.dashboard.smart_hybrid_final_provider.findData("groq_cerebras")
        )
        self.assertIn("Groq → Cerebras", self.dashboard.workflow_preview.text())
        self.assertFalse(self.dashboard.groq_api_key.isHidden())
        self.assertFalse(self.dashboard.cerebras_api_key.isHidden())
        self.assertEqual(
            [
                self.dashboard.api_test_provider.itemData(index)
                for index in range(self.dashboard.api_test_provider.count())
            ],
            ["groq", "cerebras", "glm"],
        )

    def test_hybrid_final_selector_updates_home_summary_and_visible_keys(self):
        self._choose_workflow("smart_hybrid")
        self.dashboard.smart_hybrid_final_provider.setCurrentIndex(
            self.dashboard.smart_hybrid_final_provider.findData("groq_cerebras")
        )

        self.assertIn("Groq/Cerebras 主翻译", self.dashboard.translation_summary.text())
        self.assertNotIn("Gemini 主翻译", self.dashboard.translation_summary.text())
        self.assertTrue(self.dashboard.gemini_api_key.isHidden())
        self.assertFalse(self.dashboard.groq_api_key.isHidden())
        self.assertFalse(self.dashboard.cerebras_api_key.isHidden())

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
        self.assertFalse(self.dashboard.single_streaming_mode.isHidden())
        self.assertIn(
            "当前最终模型", self.dashboard.api_test_provider.itemText(0)
        )
        self.assertNotIn(
            "cerebras",
            [
                self.dashboard.api_test_provider.itemData(index)
                for index in range(self.dashboard.api_test_provider.count())
            ],
        )
        with patch.object(
            dashboard_module.DashboardSettingsRepository,
            "save_bridge_provider",
        ):
            self.dashboard.bridge_provider.setCurrentIndex(
                self.dashboard.bridge_provider.findData("groq")
            )
        self.assertIn(
            "cerebras",
            [
                self.dashboard.api_test_provider.itemData(index)
                for index in range(self.dashboard.api_test_provider.count())
            ],
        )

    def test_disabled_apple_draft_is_reflected_in_single_model_descriptions(self):
        self._choose_workflow("single_model")
        self.dashboard.fast_translation_backend.setCurrentText("off")

        self.assertIn("草稿：关闭", self.dashboard.workflow_preview.text())
        self.assertIn("不显示本机草稿", self.dashboard.workflow_preview.text())
        self.assertIn("无本机草稿", self.dashboard.translation_summary.text())
        self.assertIn("已关闭 Apple", self.dashboard.progressive_preview_hint.text())

    def test_google_gemini_key_is_shared_with_smart_hybrid_field(self):
        self._choose_workflow("single_model")
        self.dashboard.provider.setCurrentText("Google Gemini")
        self.dashboard.api_key.setText("single-gemini-key")
        self.assertEqual(
            self.dashboard.gemini_api_key.text(), "single-gemini-key"
        )

        self._choose_workflow("smart_hybrid")
        self.assertEqual(
            self.dashboard.gemini_api_key.text(), "single-gemini-key"
        )
        self.dashboard.gemini_api_key.setText("hybrid-gemini-key")
        self.assertEqual(
            self.dashboard.provider_keys["Google Gemini"], "hybrid-gemini-key"
        )

    def test_single_model_empty_model_is_reported_as_incomplete(self):
        self._choose_workflow("single_model")
        self.dashboard.api_key.setText("test-key")
        self.dashboard.base_url.setText("https://example.com/v1")
        self.dashboard.model.setCurrentText("")

        self.dashboard._on_translation_workflow_changed()

        self.assertIn("Model ID", self.dashboard.workflow_preview.text())
        self.assertIn("缺少", self.dashboard.workflow_preview.text())

    def test_bridge_configuration_accepts_either_provider_key(self):
        self._choose_workflow("single_model")
        self.dashboard.bridge_provider.setCurrentIndex(
            self.dashboard.bridge_provider.findData("groq")
        )
        self.dashboard.groq_api_key.setText("groq-only")
        self.dashboard.cerebras_api_key.clear()
        self.dashboard._on_translation_workflow_changed()
        self.assertNotIn("缺少", self.dashboard.workflow_preview.text())

        self.dashboard.groq_api_key.clear()
        self.dashboard.cerebras_api_key.setText("cerebras-only")
        self.dashboard._on_translation_workflow_changed()
        self.assertNotIn("缺少", self.dashboard.workflow_preview.text())

    def test_switching_providers_keeps_all_edited_profiles_for_save(self):
        self._choose_workflow("single_model")
        self.dashboard.provider.setCurrentText("OpenAI")
        self.dashboard.api_key.setText("openai-edited")
        self.dashboard.model.setCurrentText("openai-edited-model")
        self.dashboard.provider.setCurrentText("Google Gemini")
        self.dashboard.api_key.setText("gemini-edited")

        profiles = self.dashboard._provider_profile_snapshot()

        self.assertEqual(profiles["OpenAI"]["api_key"], "openai-edited")
        self.assertEqual(
            profiles["OpenAI"]["selected_model"], "openai-edited-model"
        )
        self.assertEqual(
            profiles["Google Gemini"]["api_key"], "gemini-edited"
        )

    def test_model_switch_replaces_stale_price_and_saved_override_round_trips(self):
        self._choose_workflow("single_model")
        self.dashboard.provider.setCurrentText("Google Gemini")
        self.dashboard.model.setCurrentText("gemini-3.5-flash")
        self.assertEqual(self.dashboard.input_price.value(), 1.50)
        self.assertEqual(self.dashboard.output_price.value(), 9.00)

        self.dashboard.input_price.setValue(1.75)
        self.dashboard.output_price.setValue(9.25)
        profile = self.dashboard._provider_profile_snapshot()["Google Gemini"]
        self.assertEqual(profile["selected_model"], "gemini-3.5-flash")
        self.assertEqual(profile["input_price_per_million"], 1.75)
        self.assertEqual(profile["output_price_per_million"], 9.25)

    def test_speed_test_uses_the_same_explicit_course_profile_as_runtime(self):
        self._choose_workflow("single_model")
        profile_index = self.dashboard.course_profile.findData(
            "artificial-intelligence-for-planning"
        )
        self.dashboard.course_profile.setCurrentIndex(profile_index)
        self.dashboard.current_course_topic.setText(
            "Blind Search Algorithms"
        )
        spec = self.dashboard.api_test_controller._spec()

        self.assertEqual(
            spec["domain_prompt"],
            "Current lecture topic: Blind Search Algorithms.",
        )
        self.assertTrue(any(
            str(path).endswith(
                "course_profiles/artificial-intelligence-for-planning/glossary.tsv"
            )
            for path in spec["glossary_path"]
        ))

    def test_switching_from_hybrid_resets_speed_test_to_single_final_model(self):
        self._choose_workflow("smart_hybrid")
        groq_index = self.dashboard.api_test_provider.findData("groq")
        self.dashboard.api_test_provider.setCurrentIndex(groq_index)
        self._choose_workflow("single_model")
        self.assertEqual(self.dashboard.api_test_provider.currentData(), "single")

    def test_single_model_credentials_are_grouped_in_visual_order(self):
        layout = self.dashboard.translation_layout
        main_layout = self.dashboard.main_model_layout
        row = lambda widget: main_layout.getWidgetPosition(widget)[0]
        bridge_row = lambda widget: self.dashboard.bridge_layout.getWidgetPosition(widget)[0]
        self.assertLess(bridge_row(self.dashboard.bridge_provider), bridge_row(self.dashboard.groq_api_key))
        self.assertLess(
            bridge_row(self.dashboard.groq_api_key),
            bridge_row(self.dashboard.cerebras_api_key),
        )
        outer_row = lambda widget: layout.getWidgetPosition(widget)[0]
        self.assertLess(
            outer_row(self.dashboard.bridge_card),
            outer_row(self.dashboard.main_model_card),
        )
        self.assertLess(row(self.dashboard.provider), row(self.dashboard.api_key))
        self.assertLess(row(self.dashboard.api_key), row(self.dashboard.base_url))
        self.assertLess(row(self.dashboard.base_url), row(self.dashboard.model_container))
        self.assertLess(row(self.dashboard.model_container), row(self.dashboard.gemini_api_key))

    def test_main_translation_fields_are_grouped_in_a_dedicated_card(self):
        labels = " ".join(
            label.text() for label in self.dashboard.main_model_card.findChildren(QLabel)
        )
        self.assertIn("主模型", labels)
        self.assertIn("最终译文", labels)
        self.assertIsNotNone(
            self.dashboard.main_model_layout.labelForField(self.dashboard.gemini_api_key)
        )

    def test_bridge_card_explains_optional_non_blocking_behavior(self):
        labels = " ".join(
            label.text() for label in self.dashboard.bridge_card.findChildren(QLabel)
        )
        self.assertIn("可选", labels)
        self.assertIn("400 ms", labels)
        self.assertIn("非必要不建议开启", labels)
        self.assertIn("更频繁变化", labels)
        self.assertIn("不会阻塞", labels)
        with patch.object(
            dashboard_module.DashboardSettingsRepository,
            "save_bridge_provider",
        ):
            self.dashboard.bridge_provider.setCurrentIndex(
                self.dashboard.bridge_provider.findData("off")
            )
        # The selected Smart Hybrid final pool may independently need these
        # credentials even while the optional bridge itself is off.
        smart_pool = (
            self.dashboard.smart_hybrid_final_provider.currentData()
            == "groq_cerebras"
        )
        self.assertEqual(self.dashboard.groq_api_key.isHidden(), not smart_pool)
        self.assertEqual(self.dashboard.cerebras_api_key.isHidden(), not smart_pool)

    def test_bridge_toggle_and_provider_selector_stay_in_sync(self):
        self.assertGreater(
            self.dashboard.bridge_toggle.width(),
            self.dashboard.bridge_toggle.fontMetrics().horizontalAdvance("Bridge OFF") + 24,
        )
        self.assertGreaterEqual(self.dashboard.bridge_toggle.height(), 42)
        with patch.object(
            dashboard_module.DashboardSettingsRepository,
            "save_bridge_provider",
        ) as save_bridge:
            self.dashboard.bridge_toggle.click()
            self.assertEqual(self.dashboard.bridge_provider.currentData(), "groq")
            self.assertEqual(self.dashboard.bridge_toggle.text(), "Bridge ON")
            self.assertTrue(self.dashboard.bridge_toggle.isChecked())
            save_bridge.assert_called_with("groq")

            self.dashboard.bridge_toggle.click()
            self.assertEqual(self.dashboard.bridge_provider.currentData(), "off")
            self.assertEqual(self.dashboard.bridge_toggle.text(), "Bridge OFF")
            self.assertFalse(self.dashboard.bridge_toggle.isChecked())
            save_bridge.assert_called_with("off")

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
        self.assertIn("暂不通用", self.dashboard.workflow_preview.text())
        self.assertIn("桥接：关闭", self.dashboard.workflow_preview.text())
        self.assertIn("主翻译：", self.dashboard.workflow_preview.text())
        self._choose_workflow("single_model")
        preview = self.dashboard.workflow_preview.text()
        self.assertIn("主翻译", preview)
        self.assertIn("保留 Apple 草稿", preview)
        self.assertIn("最终稿", preview)

    def test_progressive_preview_hint_is_plain_and_concise(self):
        self._choose_workflow("single_model")
        hint = self.dashboard.progressive_preview_hint.text()
        self.assertIn("老师没说完", hint)
        self.assertIn("自定义模型", hint)
        self.assertNotIn("Gemini", hint)
        self.assertNotIn("OpenRouter", hint)
        self.assertNotIn("stream=true", hint)
        self.assertFalse(self.dashboard.progressive_preview_hint.isHidden())

        self._choose_workflow("apple_only")
        self.assertTrue(self.dashboard.progressive_preview_hint.isHidden())

    def test_home_exposes_progressive_preview_runtime_status(self):
        self.assertIn("Preview", self.dashboard.runtime_labels)
        self.dashboard.update_runtime_status("Preview", "ok", "ON · 0.8s")
        self.assertEqual(self.dashboard.runtime_labels["Preview"].text(), "ON · 0.8s")

    def test_usage_summary_separates_today_session_and_token_accuracy(self):
        usage = {
            "requests": 3,
            "prompt_tokens": 120,
            "completion_tokens": 60,
            "cost_usd": 0.0123,
            "estimated_cost_usd": 0.0020,
            "estimated_requests": 1,
            "estimated_prompt_tokens": 20,
            "estimated_completion_tokens": 10,
            "unpriced_requests": 0,
            "hourly_cost_usd": 0.20,
            "today": {
                "requests": 8,
                "cost_usd": 0.0456,
                "estimated_cost_usd": 0.0020,
            },
        }
        with patch.object(
            dashboard_module.session_usage_meter,
            "snapshot",
            return_value=usage,
        ):
            self.dashboard._refresh_usage_status()

        lines = self.dashboard.runtime_labels["Usage"].text().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("Today ~US$0.0456"))
        self.assertTrue(lines[1].startswith("Session ~US$0.0123"))
        self.assertIn("exact in 100 / out 50", lines[2])
        self.assertIn("estimated in 20 / out 10", lines[2])
        self.assertGreaterEqual(
            self.dashboard.runtime_labels["Usage"].minimumHeight(), 62
        )

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

    def test_profiles_edited_before_switching_to_hybrid_are_not_lost(self):
        self._choose_workflow("single_model")
        self.dashboard.provider.setCurrentText("OpenAI")
        self.dashboard.api_key.setText("edited-before-hybrid")
        self._choose_workflow("smart_hybrid")

        profiles = self.dashboard._provider_profile_snapshot()

        self.assertEqual(
            profiles["OpenAI"]["api_key"], "edited-before-hybrid"
        )

    def test_pages_explain_when_settings_take_effect(self):
        self.assertIn("重新 Launch", self.dashboard.apply_hint.text())
        self.assertIn("重新 Launch", self.dashboard.audio_panel.apply_hint.text())
        self.assertIn("重新 Launch", self.dashboard.asr_panel.apply_hint.text())

    def test_current_lecture_topic_starts_blank_for_each_app_session(self):
        self.assertEqual(self.dashboard.current_course_topic.text(), "")
        self.assertIn("session only", self.dashboard.current_course_topic.toolTip())
        self.assertTrue(
            self.dashboard.home_content.isAncestorOf(
                self.dashboard.current_course_topic
            )
        )

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
        self.assertIn("下次 Launch 生效", self.dashboard.pending_settings_label.text())

    def test_control_center_transparency_is_selectable_and_collected(self):
        self.dashboard.control_center_transparency_slider.setValue(45)

        self.assertIn("45%", self.dashboard.control_center_transparency_value.text())
        self.assertEqual(
            self.dashboard.collect_settings().control_center_transparency,
            45,
        )

        self.dashboard.control_center_transparency_slider.setValue(0)
        self.assertIn("不透明", self.dashboard.control_center_transparency_value.text())

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

    def test_smart_hint_card_exposes_an_isolated_connection_test(self):
        self.assertIn("测试连接", self.dashboard.smart_hint_test_btn.text())
        self.assertIn("不会进入课堂字幕", self.dashboard.smart_hint_test_btn.toolTip())
        self.dashboard.smart_hint_provider.setCurrentIndex(
            self.dashboard.smart_hint_provider.findData("custom")
        )
        self.dashboard.smart_hint_api_key.clear()
        self.dashboard.smart_hint_base_url.clear()
        self.dashboard.smart_hint_model.clear()
        self.dashboard._test_smart_hint()
        self.assertIn("测试失败", self.dashboard.smart_hint_status.text())
        self.assertIsNone(getattr(self.dashboard, "smart_hint_test_worker", None))

    def test_smart_hint_runtime_status_stays_single_line_with_full_detail_in_tooltip(self):
        detail = (
            "Bias-variance tradeoff in regularized estimators · "
            "keywords: bias, variance, regularization parameter, model "
            "complexity, cross-validation, generalization error"
        )
        self.dashboard.update_runtime_status("Hint", "ok", detail)
        self.assertEqual(self.dashboard.smart_hint_status.text(), "已更新")
        self.assertEqual(self.dashboard.smart_hint_status.toolTip(), detail)
        self.assertFalse(self.dashboard.smart_hint_status.wordWrap())

    def test_smart_hint_test_worker_formats_a_success_without_subtitle_events(self):
        worker = SmartHintTestWorker("key", "https://example.test/v1", "hint-model")
        messages = []
        worker.completed.connect(lambda success, detail: messages.append((success, detail)))
        fake_hint = SimpleNamespace(topic="regularization", keywords=("bias", "variance"))
        fake_client = MagicMock()
        fake_client.summarize.return_value = fake_hint
        with patch("smart_hint.SmartHintClient", return_value=fake_client):
            worker.run()
        self.assertEqual(messages, [(True, "连接成功：regularization\n关键词：bias、variance")])
        fake_client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
