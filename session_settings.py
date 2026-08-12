"""Immutable configuration captured at one Pipeline launch.

The Dashboard may keep editing and saving its controls while a lecture is
running.  A Pipeline must not observe those later edits halfway through a
sentence, so it receives this compact detached snapshot instead of the global
mutable ``config`` object.
"""

from copy import deepcopy
from types import MappingProxyType


class SessionSettingsSnapshot:
    """Read-only copy of Config's public runtime values."""

    def __init__(self, values):
        object.__setattr__(self, "_values", MappingProxyType(dict(values)))

    @classmethod
    def from_config(cls, source):
        values = {
            name: deepcopy(value)
            for name, value in vars(source).items()
            if not name.startswith("_") and name not in {"config", "config_path"}
        }
        return cls(values)

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def get(self, name, default=None):
        return self._values.get(name, default)

    def with_overrides(self, **overrides):
        """Return a new snapshot without changing the active instance."""
        values = dict(self._values)
        values.update(overrides)
        return type(self)(values)


def translation_chain(settings):
    """Human-readable immutable route shown for the active session."""
    workflow = str(settings.translation_workflow or "single_model")
    if workflow == "apple_only":
        route = "Apple 草稿（仅本机翻译）"
    elif workflow == "smart_hybrid":
        route = "Apple 草稿 → Gemini 主翻译 → GLM 兜底"
        if settings.bridge_provider == "groq":
            route = "Apple 草稿 → Groq/Cerebras 桥接 → Gemini 主翻译 → GLM 兜底"
    else:
        route = f"Apple 草稿 → {settings.single_provider or settings.model}"
        if settings.bridge_provider == "groq":
            route = f"Apple 草稿 → Groq/Cerebras 桥接 → {settings.single_provider or settings.model}"
    return route


def describe_session(settings):
    """Return concise text for the control-center active-session card."""
    parts = [translation_chain(settings)]
    topic = str(settings.current_course_topic or "").strip()
    if topic:
        parts.append(f"主题：{topic}")
    if str(settings.translation_workflow or "") == "smart_hybrid":
        parts.append("Preview：独立 Gemini 快速预览")
    elif str(settings.translation_workflow or "") != "apple_only":
        provider = settings.single_provider or settings.model
        parts.append(f"Preview：{provider} 实时预览")
    return "\n".join(parts)
