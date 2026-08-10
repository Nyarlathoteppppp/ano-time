"""Portable Single Model UI profiles; never used by the translation hot path."""

import hashlib
import json
import os
import tempfile

from keychain_store import store as default_keychain


class ProviderProfileRepository:
    """Persist provider metadata while keeping every API key in Keychain."""

    VERSION = 1

    def __init__(self, path, keychain=None):
        self.path = path
        self.keychain = keychain or default_keychain

    @staticmethod
    def _account(provider):
        digest = hashlib.sha256(provider.encode("utf-8")).hexdigest()[:16]
        return f"single_profile.{digest}"

    def _read_raw(self):
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
            profiles = document.get("profiles", {})
            return profiles if isinstance(profiles, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def load(self):
        loaded = {}
        for provider, raw in self._read_raw().items():
            if not isinstance(provider, str) or not isinstance(raw, dict):
                continue
            account = self._account(provider)
            models = raw.get("custom_models", [])
            loaded[provider] = {
                "api_key": self.keychain.resolve(raw.get("api_key", ""), account),
                "base_url": str(raw.get("base_url", "")),
                "selected_model": str(raw.get("selected_model", "")),
                "custom_models": [
                    str(item) for item in models
                    if isinstance(item, str) and item.strip()
                ],
            }
        return loaded

    def save(self, profiles):
        existing = self._read_raw()
        if not profiles:
            return
        # Update only explicitly supplied profiles. Existing profiles and their
        # Keychain references remain untouched.
        serialized = dict(existing)
        for provider, profile in sorted(profiles.items()):
            if not isinstance(provider, str) or not isinstance(profile, dict):
                continue
            account = self._account(provider)
            secret = str(profile.get("api_key", ""))
            old_reference = existing.get(provider, {}).get("api_key", "")
            old_secret = self.keychain.resolve(old_reference, account)
            reference = (
                old_reference
                if secret == old_secret
                else self.keychain.store_for_config(account, secret)
            )
            custom_models = list(dict.fromkeys(
                str(item).strip() for item in profile.get("custom_models", [])
                if str(item).strip()
            ))
            serialized[provider] = {
                "api_key": reference,
                "base_url": str(profile.get("base_url", "")),
                "selected_model": str(profile.get("selected_model", "")),
                "custom_models": custom_models,
            }

        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".provider-profiles-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {"version": self.VERSION, "profiles": serialized},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
