"""Single construction path for glass and native-notch subtitle windows."""

from dataclasses import dataclass

from native_notch_overlay import NativeNotchOverlay
from overlay_window import OverlayWindow


@dataclass(frozen=True)
class OverlaySpec:
    display_duration: object
    window_width: int
    window_height: object
    display_mode: str = "glass"
    system_audio: bool = False


def create_overlay(spec):
    """Create one overlay without leaking mode-specific options to the other."""
    mode = "notch" if spec.display_mode == "notch" else "glass"
    common = {
        "display_duration": spec.display_duration,
        "window_width": spec.window_width,
        "window_height": spec.window_height,
        "display_mode": mode,
    }
    if mode == "notch":
        return NativeNotchOverlay(**common)
    return OverlayWindow(video_overlay=bool(spec.system_audio), **common)
