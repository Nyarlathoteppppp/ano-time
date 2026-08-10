from dataclasses import dataclass


@dataclass(frozen=True)
class AudioSettings:
    device_index: object
    sample_rate: int
    silence_threshold: float
    silence_duration: float
    update_interval: float


@dataclass(frozen=True)
class TranscriptionSettings:
    backend: str
    whisper_model: str
    funasr_model: str
    device: str
    compute_type: str
    source_language: str


@dataclass(frozen=True)
class TranslationSettings:
    workflow: str
    bridge_provider: str
    single_provider: str
    api_key: str
    base_url: str
    model: str
    target_language: str
    domain: str
    fast_backend: str


@dataclass(frozen=True)
class ProviderSettings:
    deepseek_api_key: str
    siliconflow_api_key: str
    qwen_mt_api_key: str
    qwen_mt_base_url: str
    groq_api_key: str
    gemini_api_key: str
    cloudflare_account_id: str
    cloudflare_api_token: str


@dataclass(frozen=True)
class DashboardSettingsSnapshot:
    audio: AudioSettings
    transcription: TranscriptionSettings
    translation: TranslationSettings
    providers: ProviderSettings
    display_mode: str
    shortcut_enabled: bool
    shortcut_interval: float
    diagnostics_enabled: bool
    auto_save_transcripts: bool
