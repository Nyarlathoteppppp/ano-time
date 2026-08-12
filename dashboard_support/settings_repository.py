import configparser
import os

from audio_formats import normalize_sample_rate

from keychain_store import SECRET_FIELDS, store as default_keychain


class DashboardSettingsRepository:
    """Persist a dashboard snapshot without depending on Qt widgets."""

    SECTIONS = (
        "audio",
        "api",
        "translation",
        "transcription",
        "providers",
        "display",
        "shortcut",
        "diagnostics",
        "usage",
        "records",
    )

    def __init__(self, config_path, keychain=None):
        self.config_path = config_path
        self.keychain = keychain or default_keychain

    def save_bridge_provider(self, provider):
        """Persist only the bridge switch without saving unrelated edits."""
        provider = "groq" if str(provider) == "groq" else "off"
        parser = configparser.ConfigParser()
        parser.read(self.config_path)
        if not parser.has_section("translation"):
            parser.add_section("translation")
        parser.set("translation", "bridge_provider", provider)
        with open(self.config_path, "w", encoding="utf-8") as handle:
            parser.write(handle)
        os.chmod(self.config_path, 0o600)
        return provider

    def save(self, snapshot, previous_secrets=None):
        previous_secrets = dict(previous_secrets or {})
        parser = configparser.ConfigParser()
        parser.read(self.config_path)
        for section in self.SECTIONS:
            if not parser.has_section(section):
                parser.add_section(section)

        saved_secret_updates = {}

        def persist_secret(section, option, account, value):
            value = str(value or "")
            previous = previous_secrets.get(account)
            if previous is not None and value == previous:
                return parser.get(section, option, fallback="")
            stored = self.keychain.store_for_config(account, value)
            saved_secret_updates[account] = value
            return stored

        audio = snapshot.audio
        parser.set(
            "audio",
            "device_index",
            str(audio.device_index) if audio.device_index is not None else "auto",
        )
        parser.set(
            "audio",
            "sample_rate",
            str(normalize_sample_rate(
                audio.sample_rate, snapshot.transcription.backend
            )),
        )
        parser.set("audio", "silence_threshold", str(audio.silence_threshold))
        parser.set("audio", "silence_duration", str(audio.silence_duration))
        parser.set("audio", "update_interval", str(audio.update_interval))

        transcription = snapshot.transcription
        parser.set("transcription", "backend", transcription.backend)
        parser.set("transcription", "whisper_model", transcription.whisper_model)
        parser.set("transcription", "funasr_model", transcription.funasr_model)
        parser.set("transcription", "device", transcription.device)
        parser.set("transcription", "compute_type", transcription.compute_type)
        parser.set("transcription", "source_language", transcription.source_language)

        translation = snapshot.translation
        if translation.workflow == "single_model":
            parser.set(
                "api",
                "api_key",
                persist_secret(
                    "api",
                    "api_key",
                    SECRET_FIELDS[("api", "api_key")],
                    translation.api_key,
                ),
            )
            parser.set("api", "base_url", translation.base_url)
            parser.set("translation", "model", translation.model)
            parser.set(
                "translation", "input_price_per_million",
                str(translation.input_price_per_million),
            )
            parser.set(
                "translation", "output_price_per_million",
                str(translation.output_price_per_million),
            )
        parser.set("translation", "target_lang", translation.target_language)
        parser.set("translation", "domain", translation.domain)
        parser.set("translation", "course_topic", translation.course_topic)
        parser.set("translation", "fast_backend", translation.fast_backend)
        parser.set("translation", "workflow", translation.workflow)
        parser.set("translation", "bridge_provider", translation.bridge_provider)
        parser.set("translation", "single_provider", translation.single_provider)
        parser.set(
            "translation", "single_streaming_mode", translation.streaming_mode
        )
        parser.set(
            "translation",
            "provider",
            "Fast Free Pool → Qwen-MT"
            if translation.workflow == "smart_hybrid"
            else translation.single_provider,
        )

        providers = snapshot.providers
        secret_values = {
            "deepseek_api_key": providers.deepseek_api_key,
            "siliconflow_api_key": providers.siliconflow_api_key,
            "qwen_mt_api_key": providers.qwen_mt_api_key,
            "groq_api_key": providers.groq_api_key,
            "cerebras_api_key": providers.cerebras_api_key,
            "gemini_api_key": providers.gemini_api_key,
            "cloudflare_api_token": providers.cloudflare_api_token,
        }
        for option, value in secret_values.items():
            account = SECRET_FIELDS[("providers", option)]
            parser.set(
                "providers",
                option,
                persist_secret("providers", option, account, value),
            )
        parser.set("providers", "qwen_mt_base_url", providers.qwen_mt_base_url)
        parser.set(
            "providers", "cloudflare_account_id", providers.cloudflare_account_id
        )
        parser.set("display", "mode", snapshot.display_mode)
        parser.set(
            "display",
            "control_center_transparency",
            str(max(0, min(70, int(snapshot.control_center_transparency)))),
        )
        parser.set("shortcut", "enabled", str(snapshot.shortcut_enabled).lower())
        parser.set("shortcut", "double_tap_interval", str(snapshot.shortcut_interval))
        parser.set("diagnostics", "enabled", str(snapshot.diagnostics_enabled).lower())
        parser.set(
            "usage",
            "tracking_enabled",
            str(snapshot.usage_tracking_enabled).lower(),
        )
        parser.set(
            "records",
            "auto_save_transcripts",
            str(snapshot.auto_save_transcripts).lower(),
        )

        with open(self.config_path, "w", encoding="utf-8") as handle:
            parser.write(handle)
        os.chmod(self.config_path, 0o600)
        return saved_secret_updates
