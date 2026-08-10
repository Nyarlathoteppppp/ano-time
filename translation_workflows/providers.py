from translator import Translator


GROQ_NAME = "Groq GPT-OSS 20B"
CEREBRAS_NAME = "Cerebras GPT-OSS 120B"


def translator_options(config, include_course_topic=False):
    domain_prompt = config.translation_domain
    course_topic = getattr(config, "current_course_topic", "").strip()
    if include_course_topic and course_topic:
        domain_prompt = (
            f"{domain_prompt} Current lecture topic: {course_topic}."
        )
    return {
        "target_lang": config.target_lang,
        "domain_prompt": domain_prompt,
        "deadline_seconds": config.ai_deadline_seconds,
        "glossary_path": config.glossary_path,
    }


def groq_provider(config, options):
    if not config.groq_api_key:
        return None
    return {
        "name": GROQ_NAME,
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
        "priority": 3,
    }


def cerebras_provider(config, options):
    if not config.cerebras_api_key:
        return None
    return {
        "name": CEREBRAS_NAME,
        "translator": Translator(
            base_url="https://api.cerebras.ai/v1",
            api_key=config.cerebras_api_key,
            model="gpt-oss-120b",
            **options,
        ),
        # Paid bridge fallback. It is selected only after Groq is unavailable,
        # quota-limited, or cooling down.
        "priority": 4,
        "failure_cooldown_seconds": 3.0,
    }


def bridge_providers(config, options):
    """Return the ordered bridge pool without coupling it to a workflow."""
    providers = []
    for factory in (groq_provider, cerebras_provider):
        provider = factory(config, options)
        if provider:
            providers.append(provider)
    return providers
