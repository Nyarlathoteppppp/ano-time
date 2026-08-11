import json
import os
import tempfile
import unittest

from dashboard_support.provider_profiles import ProviderProfileRepository


class FakeKeychain:
    def __init__(self):
        self.values = {}

    def resolve(self, reference, account):
        return self.values.get(account, "") if reference else ""

    def store_for_config(self, account, secret):
        self.values[account] = secret
        return f"keychain://test/{account}" if secret else ""


class ProviderProfileRepositoryTests(unittest.TestCase):
    def test_round_trip_keeps_metadata_and_resolves_keychain_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "provider_profiles.json")
            keychain = FakeKeychain()
            repository = ProviderProfileRepository(path, keychain=keychain)
            repository.save({
                "OpenAI": {
                    "api_key": "secret",
                    "base_url": "https://api.openai.com/v1",
                    "selected_model": "my-model",
                    "custom_models": ["my-model", "my-model", "other-model"],
                    "input_price_per_million": 0.3,
                    "output_price_per_million": 2.5,
                }
            })

            loaded = repository.load()["OpenAI"]
            self.assertEqual(loaded["api_key"], "secret")
            self.assertEqual(loaded["selected_model"], "my-model")
            self.assertEqual(loaded["custom_models"], ["my-model", "other-model"])
            self.assertEqual(loaded["input_price_per_million"], 0.3)
            self.assertEqual(loaded["output_price_per_million"], 2.5)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            serialized = raw["profiles"]["OpenAI"]
            self.assertNotIn("secret", json.dumps(raw))
            self.assertTrue(serialized["api_key"].startswith("keychain://"))

    def test_corrupt_file_does_not_break_profile_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "provider_profiles.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not-json")
            repository = ProviderProfileRepository(path, keychain=FakeKeychain())
            self.assertEqual(repository.load(), {})

    def test_updating_one_profile_preserves_other_profile_without_keychain_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "provider_profiles.json")
            keychain = FakeKeychain()
            repository = ProviderProfileRepository(path, keychain=keychain)
            repository.save({
                "OpenAI": {
                    "api_key": "openai-secret",
                    "base_url": "https://api.openai.com/v1",
                    "selected_model": "openai-model",
                    "custom_models": [],
                }
            })
            account_count = len(keychain.values)
            repository.save({
                "Groq": {
                    "api_key": "groq-secret",
                    "base_url": "https://api.groq.com/openai/v1",
                    "selected_model": "groq-model",
                    "custom_models": [],
                }
            })
            loaded = repository.load()
            self.assertEqual(len(keychain.values), account_count + 1)
            self.assertEqual(loaded["OpenAI"]["api_key"], "openai-secret")
            self.assertEqual(loaded["Groq"]["api_key"], "groq-secret")

    def test_empty_update_does_not_create_profile_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "provider_profiles.json")
            ProviderProfileRepository(path, keychain=FakeKeychain()).save({})
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
