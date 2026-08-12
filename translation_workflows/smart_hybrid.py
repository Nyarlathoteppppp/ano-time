from hybrid_translator import HybridTranslator
from translator import Translator
from translation_usage import MeteredTranslator

from .contracts import HybridTranslatorView, TranslationWorkflow
from .providers import bridge_providers, translator_options


def _gemini_translator(config, options):
    """Build one isolated Gemini client for one translation lane."""
    return Translator(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=config.gemini_api_key,
        model="gemini-3.5-flash-lite",
        **options,
    )


def build_smart_hybrid(config, usage_path, status_callback=None):
    """Build the developer workflow with correctness-first final routing."""
    final_options = translator_options(config, include_course_topic=True)
    bridge_options = translator_options(config, include_course_topic=True)
    providers = []
    gemini_final = None
    gemini_preview = None
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
            # GLM is a fast final fallback.  Reserving the last second avoids
            # an unavailable Gemini leaving only an Apple draft on screen.
            "priority": 50,
            "terminal_fallback": True,
            "fallback_reserve_seconds": 1.0,
            "failure_cooldown_seconds": 3.0,
            "pricing_known": True,
        })
    if config.gemini_api_key:
        # Final and Preview have independent clients.  A stalled Preview must
        # not monopolize Final's connection pool or interfere with its
        # Gemini → GLM recovery path.
        gemini_final = _gemini_translator(config, final_options)
        gemini_preview = _gemini_translator(config, final_options)
        providers.append({
            "name": "Gemini 3.5 Flash-Lite Paid",
            "translator": gemini_final,
            # Correctness-first primary final model. Billing is enabled, so do
            # not apply the former free-tier RPM/TPM/RPD caps.
            "priority": 1,
            "failure_cooldown_seconds": 3.0,
            "input_price_per_million": 0.30,
            "output_price_per_million": 2.50,
            "pricing_known": True,
        })
    bridge_names = {provider["name"] for provider in bridges}
    final_names = {provider["name"] for provider in providers} - bridge_names
    if not providers:
        return TranslationWorkflow(
            name="smart_hybrid",
            final_translator=None,
            bridge_translator=None,
            final_label="Smart Hybrid · unavailable",
            preview_translator=None,
        )
    router = HybridTranslator(providers, usage_path=usage_path)
    router.status_callback = status_callback
    final = (
        HybridTranslatorView(router, excluding=bridge_names)
        if final_names else None
    )
    # Preview intentionally bypasses HybridTranslator.  It still uses the
    # same Gemini transport and is metered like every other remote request,
    # but its disposable timeout/failure can no longer mutate the final
    # Gemini → GLM router's cooldown, provider status, or failover state.
    # ProgressiveTranslationPreview already owns a separate one-active plus
    # one-latest-pending coordinator, so this lane cannot occupy Final's
    # executor workers.
    preview = (
        MeteredTranslator(
            gemini_preview,
            "Gemini 3.5 Flash-Lite Paid",
            0.30,
            2.50,
        )
        if gemini_preview is not None else None
    )
    bridge_view = (
        HybridTranslatorView(router, only=bridge_names) if bridge_names else None
    )
    return TranslationWorkflow(
        name="smart_hybrid",
        final_translator=final,
        bridge_translator=bridge_view,
        final_label="Gemini Paid → GLM fallback",
        # Preview is disposable: never wait for GLM after a Gemini miss. The
        # final route below remains Gemini -> GLM for correctness.
        preview_translator=preview,
        bridge_label="Groq → Cerebras" if bridge_view else "Off",
        final_status_managed=True,
        warmup_translator=(
            MeteredTranslator(
                gemini_final,
                "Gemini 3.5 Flash-Lite Paid",
                0.30,
                2.50,
            )
            if gemini_final is not None else None
        ),
    )
