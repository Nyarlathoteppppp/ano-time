from .apple_only import build_apple_only
from .single_model import build_single_model
from .smart_hybrid import build_smart_hybrid


BUILDERS = {
    "smart_hybrid": build_smart_hybrid,
    "single_model": build_single_model,
    "apple_only": build_apple_only,
}


def build_translation_workflow(config, usage_path, status_callback=None):
    builder = BUILDERS.get(config.translation_workflow, build_smart_hybrid)
    return builder(config, usage_path, status_callback=status_callback)
