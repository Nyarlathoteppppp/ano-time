import configparser
import os
import tempfile
import unittest

from keychain_store import KeychainStore, migrate_plaintext_secrets


class MemoryKeychain(KeychainStore):
    def __init__(self, enabled=True):
        super().__init__(service="test.realtime-ton", enabled=enabled)
        self.values = {}

    def get(self, account):
        return self.values.get(account, "")

    def set(self, account, secret):
        if not self.enabled:
            return False
        self.values[account] = secret
        return True

    def delete(self, account):
        self.values.pop(account, None)
        return True


class KeychainStoreTest(unittest.TestCase):
    def test_reference_resolves_without_exposing_secret(self):
        store = MemoryKeychain()
        reference = store.store_for_config("providers.groq", "secret-value")
        self.assertEqual(reference, "keychain://test.realtime-ton/providers.groq")
        self.assertNotIn("secret-value", reference)
        self.assertEqual(store.resolve(reference, "providers.groq"), "secret-value")

    def test_non_macos_fallback_keeps_plain_value(self):
        store = MemoryKeychain(enabled=False)
        self.assertEqual(store.store_for_config("api.default", "local-key"), "local-key")

    def test_plaintext_config_is_atomically_migrated(self):
        store = MemoryKeychain()
        parser = configparser.ConfigParser()
        parser.read_dict({
            "api": {"api_key": "old-secret"},
            "providers": {"groq_api_key": "groq-secret"},
        })
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                parser.write(handle)
            self.assertTrue(migrate_plaintext_secrets(parser, path, store))
            with open(path, encoding="utf-8") as handle:
                contents = handle.read()
            self.assertNotIn("old-secret", contents)
            self.assertNotIn("groq-secret", contents)
            self.assertIn("keychain://test.realtime-ton/api.default", contents)
            self.assertEqual(store.values["api.default"], "old-secret")
            self.assertEqual(store.values["providers.groq"], "groq-secret")

    def test_failed_migration_keeps_plaintext_file(self):
        store = MemoryKeychain(enabled=False)
        parser = configparser.ConfigParser()
        parser.read_dict({"api": {"api_key": "must-not-disappear"}})
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                parser.write(handle)
            self.assertFalse(migrate_plaintext_secrets(parser, path, store))
            with open(path, encoding="utf-8") as handle:
                contents = handle.read()
            self.assertIn("must-not-disappear", contents)

    def test_template_placeholder_is_not_saved_as_a_real_secret(self):
        store = MemoryKeychain()
        parser = configparser.ConfigParser()
        parser.read_dict({"api": {"api_key": "your-api-key"}})
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                parser.write(handle)
            self.assertFalse(migrate_plaintext_secrets(parser, path, store))

        self.assertEqual(store.values, {})


if __name__ == "__main__":
    unittest.main()
