from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationWorkflow:
    name: str
    final_translator: object | None
    bridge_translator: object | None
    final_label: str
    bridge_label: str = "Off"
    final_status_managed: bool = False
    warmup_translator: object | None = None


class HybridTranslatorView:
    """Restricted view over one quota-aware router without duplicating state."""

    def __init__(self, router, *, only=None, excluding=None):
        self.router = router
        self.only = set(only or ())
        self.excluding = set(excluding or ())

    def translate(self, *args, **kwargs):
        if self.only:
            return self.router.translate_only(self.only, *args, **kwargs)
        if self.excluding:
            return self.router.translate_excluding(self.excluding, *args, **kwargs)
        return self.router.translate(*args, **kwargs)
