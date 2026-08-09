from hybrid_translator import HybridTranslator
from translator import Translator

from .contracts import HybridTranslatorView, TranslationWorkflow
from .providers import GROQ_NAME, groq_provider, translator_options


def build_smart_hybrid(config, usage_path, status_callback=None):
    """Build the existing frozen Gemini/GLM/Qwen workflow unchanged."""
    options = translator_options(config)
    providers = []
    bridge_enabled = config.bridge_provider == "groq"
    bridge = groq_provider(config, options) if bridge_enabled else None
    if bridge:
        providers.append(bridge)
    if config.cloudflare_account_id and config.cloudflare_api_token:
        providers.append({
            "name": "Cloudflare GLM-4.7-Flash",
            "translator": Translator(
                base_url=(
                    "https://api.cloudflare.com/client/v4/accounts/"
                    f"{config.cloudflare_account_id}/ai/v1"
                ),
                api_key=config.cloudflare_api_token,
                model="@cf/zai-org/glm-4.7-flash",
                **options,
            ),
            "daily_neuron_limit": 10000,
            "neuron_input_per_million": 5500,
            "neuron_output_per_million": 36400,
            "daily_timezone": "UTC",
            "priority": 1,
        })
    if config.gemini_api_key:
        providers.append({
            "name": "Gemini 3.5 Flash-Lite",
            "translator": Translator(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=config.gemini_api_key,
                model="gemini-3.5-flash-lite",
                **options,
            ),
            "rpm_limit": 15,
            "tpm_limit": 250000,
            "daily_limit": 500,
            "daily_timezone": "America/Los_Angeles",
            "priority": 0,
        })
    if config.qwen_mt_api_key and config.qwen_mt_base_url:
        providers.append({
            "name": "Qwen-MT Flash fallback",
            "translator": Translator(
                base_url=config.qwen_mt_base_url,
                api_key=config.qwen_mt_api_key,
                model="qwen-mt-flash",
                **options,
            ),
            "priority": 99,
            "terminal_fallback": True,
            "fallback_reserve_seconds": 1.8,
            "failure_cooldown_seconds": 3.0,
        })

    final_names = {provider["name"] for provider in providers} - {GROQ_NAME}
    if not providers:
        return TranslationWorkflow(
            name="smart_hybrid",
            final_translator=None,
            bridge_translator=None,
            final_label="Smart Hybrid · unavailable",
        )
    router = HybridTranslator(providers, usage_path=usage_path)
    router.status_callback = status_callback
    final = (
        HybridTranslatorView(router, excluding={GROQ_NAME})
        if final_names else None
    )
    bridge_view = (
        HybridTranslatorView(router, only={GROQ_NAME}) if bridge else None
    )
    return TranslationWorkflow(
        name="smart_hybrid",
        final_translator=final,
        bridge_translator=bridge_view,
        final_label="Gemini/GLM → Qwen-MT",
        bridge_label=GROQ_NAME if bridge_view else "Off",
        final_status_managed=True,
    )
