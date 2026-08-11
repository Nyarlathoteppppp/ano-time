"""Built-in metadata for common Single Model choices.

Prices are UI defaults only. Saved Provider Profiles always take precedence and
the translation hot path never imports this module.
"""


MODEL_PRICES_USD_PER_MILLION = {
    ("Google Gemini", "gemini-3.5-flash-lite"): (0.30, 2.50),
    ("Google Gemini", "gemini-3.5-flash"): (1.50, 9.00),
    ("DeepSeek Official", "deepseek-v4-flash"): (0.14, 0.28),
    ("DeepSeek Official", "deepseek-chat"): (0.14, 0.28),
    ("Groq", "openai/gpt-oss-20b"): (0.075, 0.30),
    ("OpenAI", "gpt-5-mini"): (0.25, 2.00),
    ("OpenAI", "gpt-5-nano"): (0.05, 0.40),
}


def default_model_price(provider, model):
    """Return a safe built-in default, or ``(0, 0)`` for unknown pricing."""
    key = (str(provider or "").strip(), str(model or "").strip())
    return MODEL_PRICES_USD_PER_MILLION.get(key, (0.0, 0.0))
