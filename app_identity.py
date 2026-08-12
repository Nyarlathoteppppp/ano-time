"""Apply Anotime's visible identity to the Python-hosted Qt process."""

import os

from ui.qt import QIcon


APP_NAME = "Anotime"
ICON_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "assets",
    "anotime-app-icon.png",
)


def apply_app_identity(app):
    """Set Qt metadata and the native macOS Dock icon for this process."""
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(QIcon(ICON_PATH))

    try:
        from AppKit import NSApplication, NSImage

        image = NSImage.alloc().initWithContentsOfFile_(ICON_PATH)
        if image is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(image)
    except (ImportError, AttributeError):
        # Qt's application icon remains the cross-platform fallback.
        pass
