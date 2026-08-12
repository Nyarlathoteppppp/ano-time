import tempfile
import unittest
from pathlib import Path

from tools.release_audit import audit_paths, is_private_release_path


class ReleaseAuditTests(unittest.TestCase):
    def test_flags_key_shaped_secret_without_returning_secret_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_key = "gsk_" + "abcdefghijklmnopqrstuvwx1234567890"
            (root / "module.py").write_text(
                f'TOKEN = "{fake_key}"\n',
                encoding="utf-8",
            )

            findings = audit_paths(root, ["module.py"])

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].path, "module.py")
        self.assertEqual(findings[0].line, 1)
        self.assertEqual(findings[0].category, "Groq key")
        self.assertNotIn("abcdefghijkl", findings[0].describe())

    def test_allows_keychain_reference_but_blocks_private_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "keychain://com.anotime/app-key\n", encoding="utf-8"
            )

            findings = audit_paths(root, ["README.md", "config.ini"])

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].path, "config.ini")
        self.assertTrue(is_private_release_path("transcripts/lecture.txt"))
        self.assertTrue(is_private_release_path("logs/runtime.jsonl"))
        self.assertFalse(is_private_release_path("config.ini.example"))
