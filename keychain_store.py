import configparser
import os
import platform
import shutil
import subprocess
import tempfile


SERVICE = "com.nyarlathotep.realtime-ton"
REFERENCE_PREFIX = f"keychain://{SERVICE}/"

SECRET_FIELDS = {
    ("api", "api_key"): "api.default",
    ("providers", "deepseek_api_key"): "providers.deepseek",
    ("providers", "siliconflow_api_key"): "providers.siliconflow",
    ("providers", "qwen_mt_api_key"): "providers.qwen_mt",
    ("providers", "groq_api_key"): "providers.groq",
    ("providers", "cerebras_api_key"): "providers.cerebras",
    ("providers", "gemini_api_key"): "providers.gemini",
    ("providers", "cloudflare_api_token"): "providers.cloudflare",
    ("smart_hint", "api_key"): "smart_hint.api_key",
}


class KeychainStore:
    def __init__(self, service=SERVICE, enabled=None, runner=None):
        self.service = service
        self.prefix = f"keychain://{service}/"
        self.enabled = (
            platform.system() == "Darwin" and shutil.which("security") is not None
            if enabled is None else bool(enabled)
        )
        self._runner = runner or subprocess.run

    def reference(self, account):
        return f"{self.prefix}{account}"

    def is_reference(self, value):
        return str(value or "").startswith(self.prefix)

    def account_from_reference(self, value, fallback_account):
        if self.is_reference(value):
            account = str(value)[len(self.prefix):]
            return account or fallback_account
        return fallback_account

    def get(self, account):
        if not self.enabled:
            return ""
        result = self._runner(
            [
                "security", "find-generic-password", "-w",
                "-s", self.service, "-a", account,
            ],
            capture_output=True, text=True, check=False,
        )
        return result.stdout.rstrip("\n") if result.returncode == 0 else ""

    def set(self, account, secret):
        if not self.enabled or not secret:
            return False
        result = self._runner(
            [
                "security", "add-generic-password", "-U",
                "-s", self.service, "-a", account, "-w", secret,
            ],
            capture_output=True, text=True, check=False,
        )
        return result.returncode == 0

    def delete(self, account):
        if not self.enabled:
            return False
        result = self._runner(
            [
                "security", "delete-generic-password",
                "-s", self.service, "-a", account,
            ],
            capture_output=True, text=True, check=False,
        )
        return result.returncode == 0

    def resolve(self, stored_value, account):
        value = str(stored_value or "")
        if self.is_reference(value):
            return self.get(self.account_from_reference(value, account))
        return value

    def store_for_config(self, account, secret):
        secret = str(secret or "")
        if not self.enabled:
            return secret
        if not secret:
            self.delete(account)
            return ""
        if self.set(account, secret):
            return self.reference(account)
        raise RuntimeError(f"Could not save Keychain item: {account}")


store = KeychainStore()


def migrate_plaintext_secrets(parser, config_path, secret_store=store):
    """Move plaintext INI secrets to Keychain without deleting on failure."""
    if not secret_store.enabled:
        return False
    changed = False
    for (section, option), account in SECRET_FIELDS.items():
        if not parser.has_option(section, option):
            continue
        value = parser.get(section, option).strip()
        if not value or secret_store.is_reference(value):
            continue
        if value in {"dummy-key-for-local", "your-api-key"}:
            continue
        if secret_store.set(account, value):
            parser.set(section, option, secret_store.reference(account))
            changed = True
    if not changed:
        return False

    directory = os.path.dirname(config_path) or "."
    fd, temporary = tempfile.mkstemp(prefix=".config-keychain-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            parser.write(handle)
        os.chmod(temporary, 0o600)
        os.replace(temporary, config_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("[Config] Migrated plaintext API credentials to macOS Keychain")
    return True
