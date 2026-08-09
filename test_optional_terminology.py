import os
import tempfile
import unittest

from config import Config


class OptionalTerminologyConfigTests(unittest.TestCase):
    def test_new_installation_does_not_load_terminology_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "[translation]\n"
                    "glossary_path =\n"
                    "asr_corrections_path =\n"
                )
            loaded = Config(path)
            self.assertIsNone(loaded.glossary_path)
            self.assertIsNone(loaded.asr_corrections_path)

    def test_explicit_profiles_resolve_relative_to_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "[translation]\n"
                    "glossary_path = my_terms.tsv\n"
                    "asr_corrections_path = my_corrections.tsv\n"
                )
            loaded = Config(path)
            self.assertEqual(loaded.glossary_path, os.path.join(directory, "my_terms.tsv"))
            self.assertEqual(
                loaded.asr_corrections_path,
                os.path.join(directory, "my_corrections.tsv"),
            )


if __name__ == "__main__":
    unittest.main()
