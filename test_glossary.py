import os
import tempfile
import unittest
from types import SimpleNamespace

from glossary import CourseGlossary
from translator import Translator


class _RecordingCompletions:
    def __init__(self):
        self.options = None

    def create(self, **options):
        self.options = options
        message = SimpleNamespace(content="广度优先搜索是完备的。")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _RecordingClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_RecordingCompletions())


class CourseGlossaryTests(unittest.TestCase):
    def test_matches_longest_terms_without_substring_collisions(self):
        glossary = CourseGlossary(
            [
                ("search", "搜索"),
                ("breadth-first search", "广度优先搜索"),
                ("state space", "状态空间"),
            ]
        )
        matches = glossary.match(
            "Breadth-first search explores the state space, not research papers."
        )
        self.assertEqual(
            [(item.source, item.target) for item in matches],
            [("Breadth-first search", "广度优先搜索"), ("state space", "状态空间")],
        )

    def test_matches_plural_course_terms(self):
        glossary = CourseGlossary([("random variable", "随机变量")])
        matches = glossary.match("The parameters are random variables.")
        self.assertEqual(matches[0].source, "random variables")
        self.assertEqual(matches[0].target, "随机变量")

    def test_loads_editable_tsv_and_ignores_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "terms.tsv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# course terms\nmaximum likelihood estimation\t最大似然估计\n")
            glossary = CourseGlossary.from_file(path)
            self.assertEqual(len(glossary), 1)
            self.assertEqual(
                glossary.match("Use maximum likelihood estimation.")[0].target,
                "最大似然估计",
            )

    def test_qwen_mt_request_contains_only_terms_found_in_current_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "terms.tsv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "breadth-first search\t广度优先搜索\n"
                    "state space\t状态空间\n"
                )
            translator = Translator(
                api_key="test-key",
                base_url="https://example.invalid/v1",
                model="qwen-mt-flash",
                glossary_path=path,
            )
            translator.client = _RecordingClient()
            translator.translate(
                "Breadth-first search is complete.",
                use_context=False,
                remember_context=False,
            )

            options = translator.client.chat.completions.options
            translation_options = options["extra_body"]["translation_options"]
            self.assertEqual(
                translation_options["terms"],
                [{"source": "Breadth-first search", "target": "广度优先搜索"}],
            )
            self.assertNotIn("state space", str(translation_options["terms"]).casefold())


if __name__ == "__main__":
    unittest.main()
