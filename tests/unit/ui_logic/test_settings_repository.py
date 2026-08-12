import configparser
import os
import tempfile
import unittest
from dataclasses import replace

from dashboard_support.settings_repository import DashboardSettingsRepository
from dashboard_support.settings_snapshot import (
    AudioSettings,
    DashboardSettingsSnapshot,
    ProviderSettings,
    SmartHintSettings,
    TranscriptionSettings,
    TranslationSettings,
)


class FakeKeychain:
    def __init__(self):
        self.calls = []

    def store_for_config(self, account, value):
        self.calls.append((account, value))
        return f"keychain://test/{account}"


def make_snapshot(groq_key="groq-secret"):
    return DashboardSettingsSnapshot(
        audio=AudioSettings("auto", 16000, 0.005, 0.5, 0.5),
        transcription=TranscriptionSettings(
            "apple", "medium", "funasr-model", "auto", "float16", "en"
        ),
        translation=TranslationSettings(
            "smart_hybrid",
            "groq",
            "Alibaba Cloud Qwen-MT",
            "",
            "",
            "qwen-mt-flash",
            "Chinese",
            "Computer Science–AI",
            "Regularisation and bias-variance trade-off",
            "apple",
        ),
        providers=ProviderSettings(
            "deepseek-secret",
            "siliconflow-secret",
            "qwen-secret",
            "https://qwen.example/v1",
            groq_key,
            "cerebras-secret",
            "gemini-secret",
            "cloudflare-account",
            "cloudflare-secret",
        ),
        smart_hint=SmartHintSettings(
            False,
            "siliconflow",
            "hint-secret",
            "https://api.siliconflow.cn/v1",
            "deepseek-ai/DeepSeek-V4-Flash",
        ),
        display_mode="notch",
        shortcut_enabled=True,
        shortcut_interval=0.45,
        diagnostics_enabled=False,
        auto_save_transcripts=True,
    )


class DashboardSettingsRepositoryTests(unittest.TestCase):
    def test_bridge_switch_is_saved_without_overwriting_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            parser = configparser.ConfigParser()
            parser["audio"] = {"sample_rate": "48000"}
            parser["translation"] = {
                "bridge_provider": "off",
                "model": "keep-this-model",
            }
            with open(path, "w", encoding="utf-8") as handle:
                parser.write(handle)

            repository = DashboardSettingsRepository(path, keychain=FakeKeychain())
            self.assertEqual(repository.save_bridge_provider("groq"), "groq")

            saved = configparser.ConfigParser()
            saved.read(path)
            self.assertEqual(saved.get("translation", "bridge_provider"), "groq")
            self.assertEqual(saved.get("translation", "model"), "keep-this-model")
            self.assertEqual(saved.get("audio", "sample_rate"), "48000")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_unchanged_secret_keeps_reference_without_keychain_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            parser = configparser.ConfigParser()
            parser["providers"] = {
                "groq_api_key": "keychain://existing/providers.groq"
            }
            with open(path, "w", encoding="utf-8") as handle:
                parser.write(handle)
            keychain = FakeKeychain()
            repository = DashboardSettingsRepository(path, keychain=keychain)

            repository.save(
                make_snapshot(),
                previous_secrets={"providers.groq": "groq-secret"},
            )

            saved = configparser.ConfigParser()
            saved.read(path)
            self.assertEqual(
                saved.get("providers", "groq_api_key"),
                "keychain://existing/providers.groq",
            )
            self.assertNotIn(
                ("providers.groq", "groq-secret"), keychain.calls
            )

    def test_changed_secret_updates_keychain_and_returns_saved_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            keychain = FakeKeychain()
            repository = DashboardSettingsRepository(path, keychain=keychain)

            updates = repository.save(
                make_snapshot(groq_key="new-groq"),
                previous_secrets={"providers.groq": "old-groq"},
            )

            self.assertIn(("providers.groq", "new-groq"), keychain.calls)
            self.assertEqual(updates["providers.groq"], "new-groq")
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_snapshot_round_trip_preserves_workflow_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            DashboardSettingsRepository(path, keychain=FakeKeychain()).save(
                make_snapshot()
            )
            saved = configparser.ConfigParser()
            saved.read(path)

            self.assertEqual(saved.get("translation", "workflow"), "smart_hybrid")
            self.assertEqual(saved.get("translation", "bridge_provider"), "groq")
            self.assertEqual(saved.get("transcription", "source_language"), "en")
            self.assertEqual(
                saved.get("translation", "course_topic"),
                "",
            )
            self.assertEqual(saved.get("display", "mode"), "notch")
            self.assertEqual(
                saved.getint("display", "control_center_transparency"), 30
            )
            self.assertTrue(saved.getboolean("records", "auto_save_transcripts"))
            self.assertEqual(
                saved.get("translation", "single_streaming_mode"), "auto"
            )

    def test_apple_sample_rate_is_normalized_before_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            snapshot = make_snapshot()
            snapshot = replace(
                snapshot,
                audio=AudioSettings("auto", 15904, 0.005, 0.5, 0.5),
            )

            DashboardSettingsRepository(path, keychain=FakeKeychain()).save(
                snapshot
            )
            saved = configparser.ConfigParser()
            saved.read(path)
            self.assertEqual(saved.getint("audio", "sample_rate"), 16000)


if __name__ == "__main__":
    unittest.main()
