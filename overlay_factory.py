"""Single construction path for the reversible glass/notch presentation pair."""

from dataclasses import dataclass

from native_notch_overlay import NativeNotchOverlay


@dataclass(frozen=True)
class OverlaySpec:
    display_duration: object
    window_width: int
    window_height: object
    display_mode: str = "glass"
    system_audio: bool = False


def create_overlay(spec):
    """Create one presentation owner for either initial display mode.

    ``NativeNotchOverlay`` owns the semantic record store and can project it to
    either the Swift notch helper or a Qt glass delegate.  Starting directly in
    glass must still use that owner; a bare ``OverlayWindow`` cannot return to
    the native notch without rebuilding the Pipeline and losing its live
    presentation state.
    """
    mode = "notch" if spec.display_mode == "notch" else "glass"
    common = {
        "display_duration": spec.display_duration,
        "window_width": spec.window_width,
        "window_height": spec.window_height,
        "display_mode": mode,
    }
    if mode == "notch":
        return NativeNotchOverlay(**common)
    return NativeNotchOverlay(
        video_overlay=bool(spec.system_audio),
        **common,
    )
