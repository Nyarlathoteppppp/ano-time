"""Regression contract for the first PySide6 migration batch.

These modules must use ``ui.qt`` only.  The contract prevents a later edit
from bypassing the binding boundary and accidentally mixing PyQt6/PySide6.
"""

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
M1_MODULES = (
    "api_test_controller.py",
    "app_identity.py",
    "dashboard_support/workers.py",
    "global_shortcut.py",
    "subtitle_display_scheduler.py",
)
M2_PANEL_MODULES = (
    "dashboard_support/widgets.py",
    "dashboard_support/panels/asr.py",
    "dashboard_support/panels/audio.py",
    "shortcut_controller.py",
)
M3_RUNTIME_MODULES = (
    "dashboard_support/app_runtime.py",
    "dashboard.py",
)
M4_PIPELINE_MODULES = (
    "main.py",
)


class QtBindingBoundaryTests(unittest.TestCase):
    def test_m1_modules_only_import_qt_through_the_binding_boundary(self):
        for relative_path in (
            M1_MODULES + M2_PANEL_MODULES + M3_RUNTIME_MODULES + M4_PIPELINE_MODULES
        ):
            with self.subTest(module=relative_path):
                source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("from ui.qt import", source)
                self.assertNotIn("from PyQt6", source)
                self.assertNotIn("from PySide6", source)

    def test_boundary_exports_the_small_common_qt_surface(self):
        from ui import qt

        self.assertEqual(qt.QT_BINDING, "PyQt6")
        for name in ("QObject", "QThread", "QTimer", "QIcon", "Signal", "Slot"):
            self.assertTrue(hasattr(qt, name), name)


if __name__ == "__main__":
    unittest.main()
