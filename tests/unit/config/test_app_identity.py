import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app_identity


class AppIdentityTests(unittest.TestCase):
    def test_qt_identity_uses_project_icon_and_anotime_name(self):
        calls = []
        app = SimpleNamespace(
            setApplicationName=lambda value: calls.append(("name", value)),
            setApplicationDisplayName=lambda value: calls.append(("display", value)),
            setWindowIcon=lambda value: calls.append(("icon", value)),
        )
        with patch.object(app_identity, "QIcon", side_effect=lambda path: path):
            app_identity.apply_app_identity(app)

        self.assertIn(("name", "Anotime"), calls)
        self.assertIn(("display", "Anotime"), calls)
        self.assertIn(("icon", app_identity.ICON_PATH), calls)
        self.assertTrue(os.path.exists(app_identity.ICON_PATH))


if __name__ == "__main__":
    unittest.main()
