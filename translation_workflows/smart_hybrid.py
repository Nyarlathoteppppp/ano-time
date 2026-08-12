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
    final_providers = []
    gemini_final = None
    gemini_preview = None
    bridge_enabled = config.bridge_provider == "groq"
    final_pool = str(
        getattr(config, "smart_hybrid_final_provider", "gemini")
    ).lower()
    use_fast_final_pool = final_pool == "groq_cerebras"

    # Bridge and final use physically separate provider/router instances.  A
    # disposable bridge timeout, quota reservation, or cooldown must never
    # affect the selected final lane even when both lanes target Groq/Cerebras.
    bridges = bridge_providers(config, bridge_options) if bridge_enabled else []
    final_fast_pool = (
        bridge_providers(
            config,
            final_options,
            priority_start=1,
            name_suffix=" · Final",
        )
        if use_fast_final_pool else []
    )
    final_providers.extend(final_fast_pool)
    if config.cloudflare_account_id and config.cloudflare_api_token:
        final_providers.append({
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
    if config.gemini_api_key and not use_fast_final_pool:
        # Final and Preview have independent clients.  A stalled Preview must
        # not monopolize Final's connection pool or interfere with its
        # Gemini → GLM recovery path.
        gemini_final = _gemini_translator(config, final_options)
        gemini_preview = _gemini_translator(config, final_options)
        final_providers.append({
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
    if not final_providers and not bridges:
        return TranslationWorkflow(
            name="smart_hybrid",
            final_translator=None,
            bridge_translator=None,
            final_label="Smart Hybrid · unavailable",
            preview_translator=None,
        )
    final_router = (
        HybridTranslator(final_providers, usage_path=usage_path)
        if final_providers else None
    )
    if final_router is not None:
        final_router.status_callback = status_callback
    final = HybridTranslatorView(final_router) if final_router is not None else None
    # Preview intentionally bypasses HybridTranslator.  It still uses the
    # same Gemini transport and is metered like every other remote request,
    # but its disposable timeout/failure can no longer mutate the final
    # Gemini → GLM router's cooldown, provider status, or failover state.
    # ProgressiveTranslationPreview already owns a separate one-active plus
    # one-latest-pending coordinator, so this lane cannot occupy Final's
    # executor workers.
    if gemini_preview is not None:
        preview = MeteredTranslator(
            gemini_preview,
            "Gemini 3.5 Flash-Lite Paid",
            0.30,
            2.50,
        )
    elif use_fast_final_pool:
        # The fast final pool gets its own router for progressive preview.
        # Its failures and rate limits remain completely isolated from Final.
        preview_pool = bridge_providers(
            config,
            final_options,
            priority_start=1,
            name_suffix=" · Preview",
        )
        preview_router = (
            HybridTranslator(preview_pool, usage_path=usage_path)
            if preview_pool else None
        )
        if preview_router is not None:
            preview_router.status_callback = status_callback
        preview = HybridTranslatorView(preview_router) if preview_router else None
    else:
        preview = None
    bridge_router = (
        HybridTranslator(bridges, usage_path=usage_path) if bridges else None
    )
    if bridge_router is not None:
        bridge_router.status_callback = status_callback
    bridge_view = HybridTranslatorView(bridge_router) if bridge_router else None
    return TranslationWorkflow(
        name="smart_hybrid",
        final_translator=final,
        bridge_translator=bridge_view,
        final_label=(
            "Groq → Cerebras Final → GLM fallback"
            if use_fast_final_pool else "Gemini Paid → GLM fallback"
        ),
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
