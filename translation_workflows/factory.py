from .apple_only import build_apple_only
from .single_model import build_single_model
from .smart_hybrid import build_smart_hybrid


BUILDERS = {
    "smart_hybrid": build_smart_hybrid,
    "single_model": build_single_model,
    "apple_only": build_apple_only,
}


def build_translation_workflow(config, usage_path, status_callback=None):
    # Unknown/missing workflow values must fall back to the portable path.
    # Smart Hybrid depends on the project developer's specific API pool.
    builder = BUILDERS.get(config.translation_workflow, build_single_model)
    return builder(config, usage_path, status_callback=status_callback)
