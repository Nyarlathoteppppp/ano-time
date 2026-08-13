"""Keep PySide6 runtime paths and the Finder launcher safe for new installs."""

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class PySideInstallerContractTests(unittest.TestCase):
    def test_dashboard_has_no_direct_pyqt6_runtime_import(self):
        source = (PROJECT_ROOT / "dashboard.py").read_text(encoding="utf-8")
        self.assertNotIn("PyQt6.", source)
        self.assertIn("from ui.qt import", source)

    def test_install_and_hotkey_scripts_use_the_same_pyside_environment(self):
        installer = (PROJECT_ROOT / "install_mac.sh").read_text(encoding="utf-8")
        hotkey = (PROJECT_ROOT / "install_hotkey_agent.sh").read_text(
            encoding="utf-8"
        )
        starter = (PROJECT_ROOT / "start_mac.sh").read_text(encoding="utf-8")
        self.assertIn('VENV_DIR=".venv-pyside"', installer)
        self.assertIn(".venv-pyside/bin/python", hotkey)
        self.assertIn(".venv-pyside/bin/python", starter)

    def test_developer_test_entrypoints_default_to_the_pyside_environment(self):
        runner = (PROJECT_ROOT / "tools" / "run_tests.sh").read_text(
            encoding="utf-8"
        )
        guide = (PROJECT_ROOT / "tests" / "README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(".venv-pyside/bin/python", runner)
        self.assertIn(".venv-pyside/bin/python", guide)

    def test_desktop_launcher_is_rendered_for_the_install_location(self):
        template = (PROJECT_ROOT / "desktop_launcher.applescript").read_text(
            encoding="utf-8"
        )
        installer = (PROJECT_ROOT / "install_desktop_app.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("__ANOTIME_PROJECT_PATH__", template)
        self.assertIn("escaped_project_root", installer)
        self.assertIn("osacompile", installer)


if __name__ == "__main__":
    unittest.main()
