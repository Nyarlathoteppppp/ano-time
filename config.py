import configparser
import os

from keychain_store import SECRET_FIELDS, migrate_plaintext_secrets, store as keychain

class Config:
    """Centralized configuration loaded from config.ini"""
    
    def __init__(self, config_path=None):
        if config_path is None:
            # Look for config.ini in the same directory as this script
            config_path = os.path.join(os.path.dirname(__file__), "config.ini")
        self.config_path = config_path
        
        self.config = configparser.ConfigParser()
        
        if os.path.exists(config_path):
            self.config.read(config_path)
            if migrate_plaintext_secrets(self.config, config_path):
                self.config.read(config_path)
            print(f"[Config] Loaded from: {config_path}")
        else:
            print(f"[Config] Warning: {config_path} not found, using defaults/env vars")
        
        # API settings (env vars take precedence)
        self.api_base_url = os.getenv("OPENAI_BASE_URL") or self._get("api", "base_url") or None
        self.api_key = os.getenv("OPENAI_API_KEY") or self._secret(
            "api", "api_key", ""
        )
        
        # Translation settings
        self.model = self._get("translation", "model", "qwen-mt-flash")
        self.target_lang = self._get("translation", "target_lang", "Chinese")
        self.translation_domain = self._get(
            "translation",
            "domain",
            "Postgraduate Computer Science–AI coursework. Preserve standard terminology "
            "in AI, machine learning, probability and statistics, linear algebra, "
            "optimization, and software engineering.",
        )
        self.translation_threads = self._getint("translation", "threads", 4)
        self.ai_deadline_seconds = self._getfloat("translation", "ai_deadline_seconds", 3.0)
        self.fast_translation_backend = self._get(
            "translation", "fast_backend", "apple"
        ).lower()
        self.translation_provider = self._get(
            "translation", "provider", "Fast Free Pool → Qwen-MT"
        )
        configured_workflow = self._get("translation", "workflow", "").strip().lower()
        if configured_workflow not in ("smart_hybrid", "single_model", "apple_only"):
            configured_workflow = (
                "smart_hybrid"
                if self.translation_provider == "Fast Free Pool → Qwen-MT"
                else "single_model"
            )
        self.translation_workflow = configured_workflow
        configured_bridge = self._get("translation", "bridge_provider", "").strip().lower()
        if configured_bridge not in ("off", "groq"):
            configured_bridge = "groq" if configured_workflow == "smart_hybrid" else "off"
        self.bridge_provider = configured_bridge
        self.single_provider = self._get(
            "translation", "single_provider", ""
        ).strip() or (
            self.translation_provider
            if self.translation_provider != "Fast Free Pool → Qwen-MT"
            else "Alibaba Cloud Qwen-MT"
        )
        def optional_project_path(setting):
            path = self._get("translation", setting, "").strip()
            if not path:
                return None
            return path if os.path.isabs(path) else os.path.join(
                os.path.dirname(self.config_path), path
            )

        self.glossary_path = optional_project_path("glossary_path")
        self.asr_corrections_path = optional_project_path("asr_corrections_path")
        self.deepseek_api_key = self._secret("providers", "deepseek_api_key")
        self.siliconflow_api_key = self._secret("providers", "siliconflow_api_key")
        self.qwen_mt_api_key = self._secret("providers", "qwen_mt_api_key")
        self.qwen_mt_base_url = self._get("providers", "qwen_mt_base_url", "")
        self.groq_api_key = self._secret("providers", "groq_api_key")
        self.gemini_api_key = self._secret("providers", "gemini_api_key")
        self.cloudflare_account_id = self._get("providers", "cloudflare_account_id", "")
        self.cloudflare_api_token = self._secret("providers", "cloudflare_api_token")
        
        # Transcription settings
        self.asr_backend = self._get("transcription", "backend", "apple").lower()
        self.whisper_model = self._get("transcription", "whisper_model", "base")
        self.funasr_model = self._get("transcription", "funasr_model", "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch")
        self.whisper_device = self._get("transcription", "device", "auto")
        self.whisper_compute_type = self._get("transcription", "compute_type", "float16")
        self.source_language = self._get("transcription", "source_language", "en")
        if self.source_language == "auto":
            self.source_language = None  # Whisper uses None for auto-detect
        self.transcription_workers = self._getint("transcription", "transcription_workers", 4)
        
        # Audio settings
        self.sample_rate = self._getint("audio", "sample_rate", 16000)
        self.silence_threshold = self._getfloat("audio", "silence_threshold", 0.005)
        self.silence_duration = self._getfloat("audio", "silence_duration", 0.5)
        self.chunk_duration = self._getfloat("audio", "chunk_duration", 0.1)
        
        # Device index: 'system' = ScreenCaptureKit system audio; otherwise a mic index/auto.
        device_idx_str = self._get("audio", "device_index", "auto")
        if device_idx_str.isdigit():
            self.device_index = int(device_idx_str)
        elif device_idx_str.lower() in ("system", "system_audio"):
            self.device_index = "system"
        elif device_idx_str.lower() in ("auto", ""):
            # None is sounddevice's explicit representation of the current
            # macOS default input. BlackHole remains available by selecting its
            # concrete device entry in the Dashboard.
            self.device_index = None
        else:
            self.device_index = None
            
        # Max phrase duration - force processing after N seconds
        self.max_phrase_duration = self._getfloat("audio", "max_phrase_duration", 30.0)
        
        # Streaming mode settings
        self.streaming_mode = self._get("audio", "streaming_mode", "true").lower() == "true"
        self.streaming_interval = self._getfloat("audio", "streaming_interval", 3.0)
        self.streaming_step_size = self._getfloat("audio", "streaming_step_size", 0.2)
        self.update_interval = self._getfloat("audio", "update_interval", 0.5)
        self.streaming_overlap = self._getfloat("audio", "streaming_overlap", 0.3)
        self.stable_prefix_window = self._getfloat("audio", "stable_prefix_window", 0.25)
        self.stable_prefix_min_words = self._getint("audio", "stable_prefix_min_words", 3)
        
        # Display settings
        self.display_duration = self._getfloat("display", "display_duration", 10.0)
        self.window_width = self._getint("display", "window_width", 800)
        self.window_height = self._getint("display", "window_height", 120)
        self.display_mode = self._get("display", "mode", "notch").lower()

        # Session transcripts are written by a background worker and retained
        # for three days. The UI can disable the recorder entirely.
        self.auto_save_transcripts = self._getbool(
            "records", "auto_save_transcripts", True
        )

        # Global shortcut settings
        self.shortcut_enabled = self._getbool("shortcut", "enabled", True)
        self.shortcut_interval = self._getfloat("shortcut", "double_tap_interval", 0.45)

        # Diagnostics are opt-in. Normal classroom use must not start logging
        # queues, disk writers, or process resource samplers.
        self.diagnostics_enabled = self._getbool("diagnostics", "enabled", False)

        # Compatibility switch for the isolated ASR/Apple fast lane. Disable
        # only to compare against the pre-SegmentStore executor behavior.
        self.split_fast_path = self._getbool("pipeline", "split_fast_path", True)

    def reload(self):
        """Reload config.ini in place so existing module references stay valid."""
        self.__init__(self.config_path)
        return self
    
    def _get(self, section, key, fallback=""):
        try:
            value = self.config.get(section, key)
            return value if value else fallback
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback
    
    def _getint(self, section, key, fallback=0):
        try:
            return self.config.getint(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback
    
    def _getfloat(self, section, key, fallback=0.0):
        try:
            return self.config.getfloat(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback

    def _getbool(self, section, key, fallback=False):
        try:
            return self.config.getboolean(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback

    def _secret(self, section, key, fallback=""):
        raw = self._get(section, key, "")
        account = SECRET_FIELDS[(section, key)]
        resolved = keychain.resolve(raw, account)
        if resolved in {"dummy-key-for-local", "your-api-key"}:
            return fallback
        return resolved or fallback
    
    def _find_blackhole_device(self):
        """Auto-detect BlackHole audio device index"""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if d['max_input_channels'] > 0 and 'blackhole' in d['name'].lower():
                    print(f"[Config] Auto-detected BlackHole device: [{i}] {d['name']}")
                    return i
            print("[Config] BlackHole not found, using default input device")
            return None
        except Exception as e:
            print(f"[Config] Error detecting audio devices: {e}")
            return None
    
    def print_config(self):
        """Print current configuration for debugging"""
        print("[Config] Current settings:")
        print(f"  API Base URL: {self.api_base_url or '(default OpenAI)'}")
        print(f"  API Key: {'configured' if self.api_key else 'missing'}")
        print(f"  Model: {self.model}")
        print(f"  Translation Workflow: {self.translation_workflow}")
        print(f"  Bridge Provider: {self.bridge_provider}")
        print(f"  Target Language: {self.target_lang}")
        print(f"  Fast Translation: {self.fast_translation_backend}")
        print(f"  Glossary: {self.glossary_path}")
        print(f"  AI Deadline: {self.ai_deadline_seconds:.1f}s")
        print(f"  ASR Backend: {self.asr_backend}")
        print(f"  Whisper Model: {self.whisper_model}")
        print(f"  FunASR Model: {self.funasr_model}")
        print(f"  Sample Rate: {self.sample_rate}")
        print(
            "  Stable Prefix: "
            f"{self.stable_prefix_window:.2f}s / {self.stable_prefix_min_words} words"
        )

# Global config instance
config = Config()
