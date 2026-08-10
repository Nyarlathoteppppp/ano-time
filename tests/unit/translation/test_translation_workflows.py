import os
import tempfile
import unittest
from types import SimpleNamespace

from translation_workflows import build_translation_workflow


def workflow_config(**overrides):
    values = {
        "translation_workflow": "smart_hybrid",
        "bridge_provider": "groq",
        "single_provider": "Alibaba Cloud Qwen-MT",
        "target_lang": "Chinese",
        "translation_domain": "Computer Science–AI coursework.",
        "ai_deadline_seconds": 3.0,
        "glossary_path": None,
        "groq_api_key": "groq-key",
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

    def test_smart_hybrid_freezes_current_provider_order_and_qwen_policy(self):
        workflow = self._build(workflow_config())
        router = workflow.final_translator.router
        providers = {item["name"]: item for item in router.providers}

        self.assertEqual(workflow.name, "smart_hybrid")
        self.assertIs(workflow.final_translator.router, workflow.bridge_translator.router)
        self.assertEqual(providers["Gemini 3.5 Flash-Lite"]["priority"], 0)
        self.assertEqual(providers["Cloudflare GLM-4.7-Flash"]["priority"], 1)
        self.assertEqual(providers["Groq GPT-OSS 20B"]["priority"], 3)
        qwen = providers["Qwen-MT Flash fallback"]
        self.assertEqual(qwen["priority"], 99)
        self.assertEqual(qwen["fallback_reserve_seconds"], 1.8)
        self.assertEqual(qwen["failure_cooldown_seconds"], 3.0)
        self.assertEqual(workflow.final_translator.excluding, {"Groq GPT-OSS 20B"})
        self.assertEqual(workflow.bridge_translator.only, {"Groq GPT-OSS 20B"})

    def test_smart_hybrid_can_disable_bridge_without_changing_final_pool(self):
        workflow = self._build(workflow_config(bridge_provider="off"))
        names = {item["name"] for item in workflow.final_translator.router.providers}
        self.assertNotIn("Groq GPT-OSS 20B", names)
        self.assertIsNone(workflow.bridge_translator)
        self.assertIn("Qwen-MT Flash fallback", names)

    def test_single_model_has_independent_optional_bridge(self):
        workflow = self._build(
            workflow_config(
                translation_workflow="single_model",
                single_provider="Alibaba Cloud Qwen-MT",
            )
        )
        self.assertEqual(workflow.name, "single_model")
        self.assertEqual(workflow.final_translator.model, "qwen-mt-flash")
        self.assertIsNotNone(workflow.bridge_translator)
        self.assertFalse(workflow.final_status_managed)

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
