from translator import Translator
from course_profiles import (
    do_not_translate_paths,
    glossary_paths,
    profile_domain,
)


GROQ_NAME = "Groq GPT-OSS 20B"
CEREBRAS_NAME = "Cerebras GPT-OSS 120B"


def translator_options(config, include_course_topic=False):
    domain_prompt = profile_domain(
        config.translation_domain,
        getattr(config, "course_profile_id", ""),
    )
    course_topic = getattr(config, "current_course_topic", "").strip()
    if include_course_topic and course_topic:
        domain_prompt = f"Current lecture topic: {course_topic}."
    return {
        "target_lang": config.target_lang,
        "domain_prompt": domain_prompt,
        "deadline_seconds": config.ai_deadline_seconds,
        "glossary_path": glossary_paths(
            config.glossary_path,
            getattr(config, "course_profile_id", ""),
        ),
        "do_not_translate_path": do_not_translate_paths(
            getattr(config, "course_profile_id", ""),
        ),
    }


def groq_provider(config, options, *, priority=3, name_suffix=""):
    if not config.groq_api_key:
        return None
    return {
        "name": f"{GROQ_NAME}{name_suffix}",
        "translator": Translator(
            base_url="https://api.groq.com/openai/v1",
            api_key=config.groq_api_key,
            model="openai/gpt-oss-20b",
            **options,
        ),
        "rpm_limit": 30,
        "tpm_limit": 8000,
        "daily_limit": 1000,
        "daily_timezone": "UTC",
        "priority": priority,
    }


def cerebras_provider(config, options, *, priority=4, name_suffix=""):
    if not config.cerebras_api_key:
        return None
    return {
        "name": f"{CEREBRAS_NAME}{name_suffix}",
        "translator": Translator(
            base_url="https://api.cerebras.ai/v1",
            api_key=config.cerebras_api_key,
            model="gpt-oss-120b",
            **options,
        ),
        # Selected after Groq is unavailable, quota-limited, or cooling down.
        "priority": priority,
        "failure_cooldown_seconds": 3.0,
    }


def bridge_providers(config, options, *, priority_start=3, name_suffix=""):
    """Build one isolated Groq → Cerebras lane for bridge, preview, or final."""
    providers = []
    for index, factory in enumerate((groq_provider, cerebras_provider)):
        provider = factory(
            config,
            options,
            priority=priority_start + index,
            name_suffix=name_suffix,
        )
        if provider:
            providers.append(provider)
    return providers
