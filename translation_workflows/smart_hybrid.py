from hybrid_translator import HybridTranslator
from translator import Translator

from .contracts import HybridTranslatorView, TranslationWorkflow
from .providers import bridge_providers, translator_options


def build_smart_hybrid(config, usage_path, status_callback=None):
    """Build the developer hybrid workflow with free-first final routing."""
    final_options = translator_options(config, include_course_topic=True)
    bridge_options = translator_options(config, include_course_topic=True)
    providers = []
    bridge_enabled = config.bridge_provider == "groq"
    bridges = bridge_providers(config, bridge_options) if bridge_enabled else []
    providers.extend(bridges)
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
                **final_options,
            ),
            "daily_neuron_limit": 10000,
            "neuron_input_per_million": 5500,
            "neuron_output_per_million": 36400,
            "daily_timezone": "UTC",
            "priority": 1,
        })
    if config.gemini_api_key:
        providers.append({
            "name": "Gemini 3.5 Flash-Lite Paid",
            "translator": Translator(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=config.gemini_api_key,
                model="gemini-3.5-flash-lite",
                **final_options,
            ),
            # Billing is enabled for this endpoint. Do not apply the former
            # free-tier RPM/TPM/RPD caps: it is the primary paid final model
            # after free providers are unavailable or quota-limited.
            "priority": 50,
            "terminal_fallback": True,
            "fallback_reserve_seconds": 1.8,
            "failure_cooldown_seconds": 3.0,
        })
    bridge_names = {provider["name"] for provider in bridges}
    final_names = {provider["name"] for provider in providers} - bridge_names
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
        HybridTranslatorView(router, excluding=bridge_names)
        if final_names else None
    )
    bridge_view = (
        HybridTranslatorView(router, only=bridge_names) if bridge_names else None
    )
    return TranslationWorkflow(
        name="smart_hybrid",
        final_translator=final,
        bridge_translator=bridge_view,
        final_label="GLM Free → Gemini Paid",
        bridge_label="Groq → Cerebras" if bridge_view else "Off",
        final_status_managed=True,
    )
