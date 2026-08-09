from hybrid_translator import HybridTranslator
from translator import Translator

from .contracts import HybridTranslatorView, TranslationWorkflow
from .providers import GROQ_NAME, groq_provider, translator_options


def _single_endpoint(config):
    provider = config.single_provider
    if provider == "Alibaba Cloud Qwen-MT":
        return (
            config.qwen_mt_base_url,
            config.qwen_mt_api_key,
            "qwen-mt-flash",
            "Qwen-MT Flash",
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
    options = translator_options(config)
    base_url, api_key, model, label = _single_endpoint(config)
    final = None
    if base_url and api_key and model:
        final = Translator(
            base_url=base_url,
            api_key=api_key,
            model=model,
            **options,
        )

    bridge_view = None
    if config.bridge_provider == "groq":
        bridge = groq_provider(config, options)
        if bridge:
            router = HybridTranslator([bridge], usage_path=usage_path)
            router.status_callback = status_callback
            bridge_view = HybridTranslatorView(router, only={GROQ_NAME})

    return TranslationWorkflow(
        name="single_model",
        final_translator=final,
        bridge_translator=bridge_view,
        final_label=label or config.single_provider,
        bridge_label=GROQ_NAME if bridge_view else "Off",
        final_status_managed=False,
    )
