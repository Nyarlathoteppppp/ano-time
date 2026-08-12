import unittest
from types import SimpleNamespace

from session_settings import SessionSettingsSnapshot, describe_session


class SessionSettingsSnapshotTests(unittest.TestCase):
    def test_snapshot_detaches_values_and_accepts_session_only_override(self):
        source = SimpleNamespace(
            translation_workflow="smart_hybrid",
            bridge_provider="off",
            single_provider="unused",
            model="unused",
            current_course_topic="old topic",
            course_profile_id="statistical-machine-learning",
            nested={"items": ["before"]},
        )

        snapshot = SessionSettingsSnapshot.from_config(source).with_overrides(
            current_course_topic="Current lecture"
        )
        source.nested["items"].append("after")
        source.current_course_topic = "changed later"

        self.assertEqual(snapshot.current_course_topic, "Current lecture")
        self.assertEqual(snapshot.nested, {"items": ["before"]})
        self.assertIn("Gemini 主翻译", describe_session(snapshot))
        self.assertIn("主题：Current lecture", describe_session(snapshot))
        self.assertIn("档案：Statistical Machine Learning", describe_session(snapshot))

    def test_single_model_description_uses_session_route(self):
        settings = SessionSettingsSnapshot({
            "translation_workflow": "single_model",
            "bridge_provider": "off",
            "single_provider": "OpenAI",
            "model": "gpt-test",
            "current_course_topic": "",
        })

        self.assertEqual(
            describe_session(settings),
            "Apple 草稿 → OpenAI\nPreview：OpenAI 实时预览",
        )

    def test_single_model_description_reflects_disabled_apple_draft(self):
        settings = SessionSettingsSnapshot({
            "translation_workflow": "single_model",
            "bridge_provider": "off",
            "single_provider": "OpenAI",
            "model": "gpt-test",
            "current_course_topic": "",
            "fast_translation_backend": "off",
        })

        self.assertEqual(
            describe_session(settings),
            "无本机草稿 → OpenAI\nPreview：OpenAI 实时预览",
        )


if __name__ == "__main__":
    unittest.main()
