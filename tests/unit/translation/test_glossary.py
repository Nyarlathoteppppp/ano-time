import os
import tempfile
import unittest
from types import SimpleNamespace

from glossary import ASRCorrections, CourseGlossary
from course_profiles import correction_paths, glossary_paths, resolve_course_profile
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
    def test_comp90054_profile_requires_explicit_matching_topic(self):
        self.assertIsNone(resolve_course_profile(""))
        self.assertIsNone(resolve_course_profile("Statistical Machine Learning"))
        profile = resolve_course_profile("COMP90054 Blind Search Algorithms")
        self.assertEqual(profile.name, "COMP90054 Planning for Autonomy")
        self.assertEqual(len(glossary_paths("base.tsv", "blind search")), 2)
        self.assertEqual(len(correction_paths("base.tsv", "blind search")), 2)

    def test_comp90054_profile_corrects_observed_planning_asr_errors(self):
        corrections = ASRCorrections.from_files(
            correction_paths(None, "Planning for Autonomy: blind search")
        )
        self.assertEqual(
            corrections.apply(
                "Breath research uses a PriorityQ and checks the gold state."
            ),
            "breadth-first search uses a priority queue and checks the goal state.",
        )
    def test_finalized_asr_corrections_are_boundary_safe(self):
        corrections = ASRCorrections([
            ("Ajail", "Agile"),
            ("code and fixed", "code and fix"),
        ])
        self.assertEqual(
            corrections.apply("Ajail does not mean code and fixed development."),
            "Agile does not mean code and fix development.",
        )
        self.assertEqual(corrections.apply("Ajailable"), "Ajailable")

    def test_sml_asr_corrections_fix_observed_high_confidence_errors(self):
        corrections = ASRCorrections.from_file("asr_corrections.tsv")
        self.assertEqual(
            corrections.apply(
                "Discriminalysis uses a coverance matrix for load dimensional plots."
            ),
            "discriminant analysis uses a covariance matrix for low-dimensional plots.",
        )

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
            self.assertIn("source comes from ASR", translation_options["domains"])

    def test_generic_model_prompt_requests_conservative_asr_correction(self):
        translator = Translator(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="generic-fast-model",
        )
        translator.client = _RecordingClient()
        translator.translate(
            "The bread first search is complete.",
            use_context=False,
            remember_context=False,
        )

        system_prompt = translator.client.chat.completions.options["messages"][0]["content"]
        self.assertIn(
            "The source comes from ASR and may contain recognition errors.",
            system_prompt,
        )
        self.assertIn(
            "Return only the complete Simplified Chinese translation of CURRENT.",
            system_prompt,
        )
        self.assertIn("mathematical variable, operator", system_prompt)
        self.assertIn("as inline LaTeX", system_prompt)
        self.assertIn("never transliterate symbol names", system_prompt)
        self.assertIn("No Markdown or explanations", system_prompt)

    def test_context_prompt_forbids_notes_and_returns_current_translation_only(self):
        translator = Translator(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="generic-fast-model",
        )
        translator.client = _RecordingClient()
        translator.translate(
            "We fit a model.",
            context_text="The lecture discusses linear regression.",
            remember_context=False,
        )

        system_prompt = translator.client.chat.completions.options["messages"][0]["content"]
        self.assertIn("Use CONTEXT only for references and terminology", system_prompt)
        self.assertIn("translation of CURRENT", system_prompt)

    def test_previous_preview_prompt_preserves_valid_words_without_locking_errors(self):
        translator = Translator(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="generic-fast-model",
        )
        translator.client = _RecordingClient()
        translator.translate(
            "The small dog likes eating strawberries.",
            previous_preview="这个人很喜欢吃西瓜。",
            context_text="The lecture discusses classification.",
            remember_context=False,
        )

        messages = translator.client.chat.completions.options["messages"]
        self.assertIn("Correctness overrides continuity", messages[0]["content"])
        self.assertIn(
            "Preserve wording from PREVIOUS only where it remains accurate",
            messages[0]["content"],
        )
        self.assertIn("PREVIOUS:\n这个人很喜欢吃西瓜。", messages[1]["content"])
        self.assertIn("CURRENT:\nThe small dog", messages[1]["content"])

    def test_fast_pool_uses_provider_compatible_latency_options(self):
        groq = Translator(
            api_key="test-key",
            base_url="https://api.groq.com/openai/v1",
            model="openai/gpt-oss-20b",
        )
        groq.client = _RecordingClient()
        groq.translate("Translate this.", use_context=False, remember_context=False)
        self.assertEqual(
            groq.client.chat.completions.options["reasoning_effort"], "low"
        )

        cerebras = Translator(
            api_key="test-key",
            base_url="https://api.cerebras.ai/v1",
            model="gpt-oss-120b",
        )
        cerebras.client = _RecordingClient()
        cerebras.translate(
            "Translate this.", use_context=False, remember_context=False
        )
        self.assertEqual(
            cerebras.client.chat.completions.options["reasoning_effort"],
            "low",
        )

        gemini = Translator(
            api_key="test-key",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model="gemini-3.5-flash-lite",
        )
        gemini.client = _RecordingClient()
        gemini.translate("Translate this.", use_context=False, remember_context=False)
        self.assertNotIn("temperature", gemini.client.chat.completions.options)
        self.assertEqual(
            gemini.client.chat.completions.options["reasoning_effort"],
            "minimal",
        )

        cloudflare = Translator(
            api_key="test-key",
            base_url="https://api.cloudflare.com/client/v4/accounts/test/ai/v1",
            model="@cf/zai-org/glm-4.7-flash",
        )
        cloudflare.client = _RecordingClient()
        cloudflare.translate("Translate this.", use_context=False, remember_context=False)
        self.assertEqual(
            cloudflare.client.chat.completions.options["extra_body"],
            {"chat_template_kwargs": {"enable_thinking": False}},
        )


if __name__ == "__main__":
    unittest.main()
