from translator import Translator


GROQ_NAME = "Groq GPT-OSS 20B"


def translator_options(config):
    return {
        "target_lang": config.target_lang,
        "domain_prompt": config.translation_domain,
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
