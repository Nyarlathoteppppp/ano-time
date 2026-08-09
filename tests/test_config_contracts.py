import os
import tempfile
import unittest
from unittest.mock import patch

import config as config_module


class ConfigContractTests(unittest.TestCase):
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
