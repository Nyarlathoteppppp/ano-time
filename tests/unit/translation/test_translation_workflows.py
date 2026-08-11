import os
import tempfile
import unittest
from types import SimpleNamespace

from translation_workflows import build_translation_workflow


class _NamedTranslator:
    def __init__(self, name):
        self.name = name
        self.calls = 0

    def translate(self, *_args, **_kwargs):
        self.calls += 1
        return self.name


def workflow_config(**overrides):
    values = {
        "translation_workflow": "smart_hybrid",
        "bridge_provider": "groq",
        "single_provider": "Alibaba Cloud Qwen-MT",
        "target_lang": "Chinese",
        "translation_domain": "Computer Science–AI coursework.",
        "current_course_topic": "Regularisation and bias-variance trade-off",
        "ai_deadline_seconds": 3.0,
        "glossary_path": None,
        "groq_api_key": "groq-key",
        "cerebras_api_key": "cerebras-key",
        "gemini_api_key": "gemini-key",
        "cloudflare_account_id": "cloudflare-account",
        "cloudflare_api_token": "cloudflare-token",
        "qwen_mt_api_key": "qwen-key",
        "qwen_mt_base_url": "https://qwen.example/v1",
        "api_base_url": "https://custom.example/v1",
        "api_key": "custom-key",
        "model": "custom-model",
        "deepseek_api_key": "deepseek-key",
        "siliconflow_api_key": "siliconflow-key",
        "single_streaming_mode": "auto",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TranslationWorkflowTests(unittest.TestCase):
    def _build(self, config):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return build_translation_workflow(
            config,
            os.path.join(directory.name, "usage.json"),
        )

    def test_smart_hybrid_uses_paid_gemini_before_glm_fallback(self):
        workflow = self._build(workflow_config())
        router = workflow.final_translator.router
        providers = {item["name"]: item for item in router.providers}

        self.assertEqual(workflow.name, "smart_hybrid")
        self.assertIs(workflow.final_translator.router, workflow.bridge_translator.router)
        gemini = providers["Gemini 3.5 Flash-Lite Paid"]
        glm = providers["Cloudflare GLM-4.7-Flash"]
        self.assertEqual(gemini["priority"], 1)
        self.assertEqual(glm["priority"], 50)
        self.assertFalse(gemini["terminal_fallback"])
        self.assertTrue(glm["terminal_fallback"])
        self.assertIs(workflow.warmup_translator.translator, gemini["translator"])
        self.assertEqual(gemini["input_price_per_million"], 0.30)
        self.assertEqual(gemini["output_price_per_million"], 2.50)
        self.assertEqual(glm["fallback_reserve_seconds"], 1.0)
        self.assertIsNone(gemini["rpm_limit"])
        self.assertIsNone(gemini["tpm_limit"])
        self.assertIsNone(gemini["daily_limit"])
        self.assertEqual(providers["Groq GPT-OSS 20B"]["priority"], 3)
        self.assertEqual(providers["Cerebras GPT-OSS 120B"]["priority"], 4)
        self.assertIn(
            "Current lecture topic: Regularisation and bias-variance trade-off",
            providers["Cloudflare GLM-4.7-Flash"]["translator"].domain_prompt,
        )
        self.assertIn(
            "Current lecture topic: Regularisation and bias-variance trade-off",
            providers["Groq GPT-OSS 20B"]["translator"].domain_prompt,
        )
        self.assertNotIn(
            "Computer Science–AI coursework",
            providers["Cloudflare GLM-4.7-Flash"]["translator"].domain_prompt,
        )
        self.assertNotIn("Qwen-MT Flash fallback", providers)
        self.assertEqual(workflow.final_label, "Gemini Paid → GLM fallback")
        bridge_names = {"Groq GPT-OSS 20B", "Cerebras GPT-OSS 120B"}
        self.assertEqual(workflow.final_translator.excluding, bridge_names)
        self.assertEqual(workflow.bridge_translator.only, bridge_names)

    def test_smart_hybrid_can_disable_bridge_without_changing_final_pool(self):
        workflow = self._build(workflow_config(bridge_provider="off"))
        names = {item["name"] for item in workflow.final_translator.router.providers}
        self.assertNotIn("Groq GPT-OSS 20B", names)
        self.assertIsNone(workflow.bridge_translator)
        self.assertIn("Gemini 3.5 Flash-Lite Paid", names)
        self.assertNotIn("Qwen-MT Flash fallback", names)

    def test_blank_current_course_topic_is_not_injected(self):
        workflow = self._build(workflow_config(current_course_topic=""))
        for provider in workflow.final_translator.router.providers:
            self.assertNotIn(
                "Current lecture topic:", provider["translator"].domain_prompt
            )

    def test_bridge_uses_cerebras_after_groq_daily_quota_and_returns_to_groq(self):
        workflow = self._build(workflow_config())
        router = workflow.bridge_translator.router
        providers = {provider["name"]: provider for provider in router.providers}
        groq = providers["Groq GPT-OSS 20B"]
        cerebras = providers["Cerebras GPT-OSS 120B"]
        groq_fake = _NamedTranslator("groq")
        cerebras_fake = _NamedTranslator("cerebras")
        groq["translator"] = groq_fake
        cerebras["translator"] = cerebras_fake

        router._usage[groq["name"]] = {
            "date": router._today(groq),
            "attempts": groq["daily_limit"],
        }
        self.assertEqual(workflow.bridge_translator.translate("first"), "cerebras")
        self.assertEqual((groq_fake.calls, cerebras_fake.calls), (0, 1))

        # Simulate the persisted daily counter resetting on the next quota day.
        router._usage[groq["name"]] = {
            "date": "expired-day",
            "attempts": groq["daily_limit"],
        }
        groq["cooldown_until"] = 0.0
        groq["daily_block_date"] = None
        self.assertEqual(workflow.bridge_translator.translate("second"), "groq")
        self.assertEqual((groq_fake.calls, cerebras_fake.calls), (1, 1))

    def test_single_model_has_independent_optional_bridge(self):
        workflow = self._build(
            workflow_config(
                translation_workflow="single_model",
                single_provider="Alibaba Cloud Qwen-MT",
                model="qwen-mt-flash",
            )
        )
        self.assertEqual(workflow.name, "single_model")
        self.assertEqual(workflow.final_translator.model, "qwen-mt-flash")
        self.assertIsNotNone(workflow.bridge_translator)
        self.assertEqual(
            workflow.bridge_translator.only,
            {"Groq GPT-OSS 20B", "Cerebras GPT-OSS 120B"},
        )
        self.assertFalse(workflow.final_status_managed)

    def test_single_qwen_uses_the_model_selected_in_control_center(self):
        workflow = self._build(
            workflow_config(
                translation_workflow="single_model",
                single_provider="Alibaba Cloud Qwen-MT",
                model="qwen-mt-plus",
                bridge_provider="off",
            )
        )
        self.assertEqual(workflow.final_translator.model, "qwen-mt-plus")

    def test_single_model_runtime_receives_portable_control_values(self):
        workflow = self._build(
            workflow_config(
                translation_workflow="single_model",
                single_provider="Custom OpenAI-Compatible",
                api_base_url="https://portable.example/v1",
                api_key="portable-key",
                model="vendor/live-translation",
                target_lang="Japanese",
                current_course_topic="Graph search and admissible heuristics",
                bridge_provider="off",
                input_price_per_million=0.25,
                output_price_per_million=1.5,
                single_streaming_mode="off",
            )
        )

        translator = workflow.final_translator
        self.assertEqual(translator.mode, "off")
        self.assertEqual(translator.base_url, "https://portable.example/v1")
        self.assertEqual(translator.model, "vendor/live-translation")
        self.assertEqual(translator.target_lang, "Japanese")
        self.assertEqual(
            translator.domain_prompt,
            "Current lecture topic: Graph search and admissible heuristics.",
        )
        self.assertEqual(translator.translator.input_price, 0.25)
        self.assertEqual(translator.translator.output_price, 1.5)
        self.assertIsNone(workflow.bridge_translator)

    def test_smart_hybrid_does_not_use_single_streaming_adapter(self):
        workflow = self._build(workflow_config(single_streaming_mode="off"))
        self.assertFalse(hasattr(workflow.final_translator, "mode"))

    def test_apple_only_initializes_no_remote_clients(self):
        workflow = self._build(
            workflow_config(translation_workflow="apple_only")
        )
        self.assertIsNone(workflow.final_translator)
        self.assertIsNone(workflow.bridge_translator)

    def test_unknown_workflow_falls_back_to_portable_single_model(self):
        workflow = self._build(
            workflow_config(
                translation_workflow="unknown",
                single_provider="Alibaba Cloud Qwen-MT",
            )
        )
        self.assertEqual(workflow.name, "single_model")


if __name__ == "__main__":
    unittest.main()
