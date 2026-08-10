import os
import tempfile
import unittest
from unittest.mock import patch

import config as config_module


class ConfigContractTests(unittest.TestCase):
    def test_missing_config_uses_current_realtime_classroom_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "missing.ini")
            with patch.object(config_module.keychain, "resolve", return_value=""):
                loaded = config_module.Config(path)

        self.assertEqual(loaded.asr_backend, "apple")
        self.assertEqual(loaded.source_language, "en")
        self.assertEqual(loaded.fast_translation_backend, "apple")
        self.assertEqual(loaded.display_mode, "notch")
        self.assertEqual(loaded.model, "qwen-mt-flash")
        self.assertEqual(loaded.api_key, "")
        self.assertIsNone(loaded.device_index)
        self.assertTrue(loaded.auto_save_transcripts)

    def test_auto_audio_uses_macos_default_instead_of_blackhole(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("[audio]\ndevice_index = auto\n")
            with (
                patch.object(config_module.keychain, "resolve", return_value=""),
                patch.object(
                    config_module.Config,
                    "_find_blackhole_device",
                    side_effect=AssertionError("BlackHole must not be auto-selected"),
                ),
            ):
                loaded = config_module.Config(path)

        self.assertIsNone(loaded.device_index)

    def test_system_audio_deadline_and_relative_profiles_load_together(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "[audio]\n"
                    "device_index = system_audio\n"
                    "[translation]\n"
                    "ai_deadline_seconds = 3\n"
                    "glossary_path = terms.tsv\n"
                    "asr_corrections_path = corrections.tsv\n"
                    "[transcription]\n"
                    "source_language = auto\n"
                )
            with patch.object(config_module.keychain, "resolve", return_value=""):
                loaded = config_module.Config(path)

            self.assertEqual(loaded.device_index, "system")
            self.assertEqual(loaded.ai_deadline_seconds, 3.0)
            self.assertEqual(loaded.glossary_path, os.path.join(directory, "terms.tsv"))
            self.assertEqual(
                loaded.asr_corrections_path,
                os.path.join(directory, "corrections.tsv"),
            )
            self.assertIsNone(loaded.source_language)
            self.assertFalse(loaded.diagnostics_enabled)
            self.assertTrue(loaded.split_fast_path)
            self.assertEqual(loaded.translation_workflow, "smart_hybrid")
            self.assertEqual(loaded.bridge_provider, "groq")

    def test_legacy_single_provider_migrates_without_enabling_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "[translation]\n"
                    "provider = DeepSeek Official\n"
                    "model = deepseek-v4-flash\n"
                )
            with patch.object(config_module.keychain, "resolve", return_value=""):
                loaded = config_module.Config(path)
            self.assertEqual(loaded.translation_workflow, "single_model")
            self.assertEqual(loaded.bridge_provider, "off")
            self.assertEqual(loaded.single_provider, "DeepSeek Official")

    def test_explicit_workflow_controls_bridge_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "[translation]\n"
                    "provider = Fast Free Pool → Qwen-MT\n"
                    "workflow = single_model\n"
                    "bridge_provider = groq\n"
                    "single_provider = Alibaba Cloud Qwen-MT\n"
                )
            with patch.object(config_module.keychain, "resolve", return_value=""):
                loaded = config_module.Config(path)
            self.assertEqual(loaded.translation_workflow, "single_model")
            self.assertEqual(loaded.bridge_provider, "groq")
            self.assertEqual(loaded.single_provider, "Alibaba Cloud Qwen-MT")

    def test_diagnostics_require_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("[diagnostics]\nenabled = true\n")
            with patch.object(config_module.keychain, "resolve", return_value=""):
                loaded = config_module.Config(path)
            self.assertTrue(loaded.diagnostics_enabled)

    def test_keychain_reference_is_resolved_by_config_layer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "[providers]\n"
                    "groq_api_key = keychain://com.nyarlathotep.realtime-ton/providers.groq\n"
                )
            with patch.object(
                config_module.keychain,
                "resolve",
                side_effect=lambda value, account: (
                    "resolved-secret" if account == "providers.groq" else value
                ),
            ):
                loaded = config_module.Config(path)

            self.assertEqual(loaded.groq_api_key, "resolved-secret")


if __name__ == "__main__":
    unittest.main()
