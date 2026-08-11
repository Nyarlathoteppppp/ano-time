"""Minimal macOS backing transparency without blur windows or polling."""

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


def apply_native_transparency(widget):
    """Clear only the NSWindow backing surface; never create child windows."""
    window = native_window(widget)
    if window is None:
        return False
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    window.setTitlebarAppearsTransparent_(False)
    return True
