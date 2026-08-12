"""Deterministic Dashboard configuration for UI workflow tests.

The real Dashboard reads the user's ignored ``config.ini``.  Tests must never
depend on that file, its Keychain references, or whichever workflow happens to
be configured on a developer machine.
"""

from config import Config


def make_dashboard_config(config_path):
    """Return an isolated, fully configured Dashboard test configuration."""
    settings = Config(config_path)

    # Keep test credentials in memory only.  Writing dummy values to an INI
    # would exercise the macOS Keychain migration path and leak test state into
    # the developer's login keychain.
    settings.api_base_url = "https://api.example.invalid/v1"
    settings.api_key = "test-api-key"
    settings.deepseek_api_key = "test-deepseek-key"
    settings.siliconflow_api_key = "test-siliconflow-key"
    settings.qwen_mt_api_key = "test-qwen-key"
    settings.qwen_mt_base_url = "https://qwen.example.invalid/v1"
    settings.groq_api_key = "test-groq-key"
    settings.cerebras_api_key = "test-cerebras-key"
    settings.gemini_api_key = "test-gemini-key"
    settings.cloudflare_account_id = "test-account"
    settings.cloudflare_api_token = "test-cloudflare-token"
    settings.smart_hint_api_key = "test-hint-key"

    # These assertions describe the supported first-run experience, rather
    # than the current developer's persisted choice.
    settings.translation_provider = "Fast Free Pool → Qwen-MT"
    settings.translation_workflow = "smart_hybrid"
    settings.smart_hybrid_final_provider = "gemini"
    settings.bridge_provider = "off"
    settings.single_provider = "Alibaba Cloud Qwen-MT"
    settings.model = "qwen-mt-flash"
    settings.fast_translation_backend = "apple"
    settings.single_streaming_mode = "auto"
    return settings
