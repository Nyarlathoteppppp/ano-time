"""Minimal macOS window backing control without blur views or polling."""

try:
    from ctypes import c_void_p

    from AppKit import NSColor
    import objc

    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False


def native_window(widget):
    if not HAS_APPKIT:
        return None
    try:
        ns_view = objc.objc_object(c_void_p=c_void_p(int(widget.winId())))
        return ns_view.window()
    except Exception:
        return None


def apply_window_backing(widget, transparency_percent):
    """Switch the existing NSWindow between clear and opaque backing."""
    window = native_window(widget)
    if window is None:
        return False
    transparent = int(transparency_percent or 0) > 0
    window.setOpaque_(not transparent)
    window.setBackgroundColor_(
        NSColor.clearColor()
        if transparent
        else NSColor.windowBackgroundColor()
    )
    window.setTitlebarAppearsTransparent_(False)
    return True
