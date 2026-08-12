from hybrid_translator import HybridTranslator
from translator import Translator
from translation_usage import MeteredTranslator

from .contracts import HybridTranslatorView, TranslationWorkflow
from .providers import bridge_providers, translator_options
from .single_streaming import SingleModelStreamingAdapter


def _single_endpoint(config):
    provider = config.single_provider
    if provider == "Alibaba Cloud Qwen-MT":
        return (
            config.qwen_mt_base_url,
            config.qwen_mt_api_key,
            config.model or "qwen-mt-flash",
            config.model or "Qwen-MT Flash",
        )
    if provider == "DeepSeek Official":
        return (
            "https://api.deepseek.com",
            config.deepseek_api_key or config.api_key,
            config.model,
            config.model,
        )
    if provider == "SiliconFlow":
        return (
            "https://api.siliconflow.cn/v1",
            config.siliconflow_api_key,
            config.model,
            config.model,
        )
    return config.api_base_url, config.api_key, config.model, config.model


def build_single_model(config, usage_path, status_callback=None):
    final_options = translator_options(config, include_course_topic=True)
    bridge_options = translator_options(config, include_course_topic=True)
    base_url, api_key, model, label = _single_endpoint(config)
    final = None
    if base_url and api_key and model:
        metered = MeteredTranslator(Translator(
            base_url=base_url,
            api_key=api_key,
            model=model,
            **final_options,
        ), label or config.single_provider,
            getattr(config, "input_price_per_million", 0.0),
            getattr(config, "output_price_per_million", 0.0),
        )
        final = SingleModelStreamingAdapter(
            metered,
            getattr(config, "single_streaming_mode", "auto"),
        )

    bridge_view = None
    if config.bridge_provider == "groq":
        bridges = bridge_providers(config, bridge_options)
        if bridges:
            router = HybridTranslator(bridges, usage_path=usage_path)
            router.status_callback = status_callback
            bridge_view = HybridTranslatorView(
                router, only={provider["name"] for provider in bridges}
            )

    return TranslationWorkflow(
        name="single_model",
        final_translator=final,
        bridge_translator=bridge_view,
        final_label=label or config.single_provider,
        # A portable single endpoint has no secondary preview fallback. The
        # preview deadline may discard slow work; finalization still uses the
        # same endpoint with its full correctness budget.
        preview_translator=final,
        bridge_label="Groq → Cerebras" if bridge_view else "Off",
        final_status_managed=False,
        warmup_translator=(
            final
            if final is not None
            and "generativelanguage.googleapis.com" in str(base_url)
            and str(model).startswith("gemini-")
            else None
        ),
    )
