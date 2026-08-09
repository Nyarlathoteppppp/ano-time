from .contracts import TranslationWorkflow


def build_apple_only(_config, _usage_path, status_callback=None):
    return TranslationWorkflow(
        name="apple_only",
        final_translator=None,
        bridge_translator=None,
        final_label="Apple on-device only",
    )
