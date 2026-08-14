import unittest
from unittest.mock import patch

from overlay_factory import OverlaySpec, create_overlay


class OverlayFactoryTests(unittest.TestCase):
    def spec(self, **changes):
        values = {
            "display_duration": 5,
            "window_width": 640,
            "window_height": 360,
            "display_mode": "glass",
            "system_audio": False,
        }
        values.update(changes)
        return OverlaySpec(**values)

    @patch("overlay_factory.NativeNotchOverlay")
    def test_microphone_glass_uses_reversible_presentation_owner(self, overlay_class):
        created = create_overlay(self.spec())

        self.assertIs(created, overlay_class.return_value)
        overlay_class.assert_called_once_with(
            display_duration=5,
            window_width=640,
            window_height=360,
            display_mode="glass",
            video_overlay=False,
        )

    @patch("overlay_factory.NativeNotchOverlay")
    def test_system_audio_glass_preserves_video_overlay_mode(self, overlay_class):
        create_overlay(self.spec(system_audio=True))

        self.assertTrue(overlay_class.call_args.kwargs["video_overlay"])

    @patch("overlay_factory.NativeNotchOverlay")
    def test_native_notch_never_receives_glass_only_options(self, notch_class):
        created = create_overlay(
            self.spec(display_mode="notch", system_audio=True)
        )

        self.assertIs(created, notch_class.return_value)
        self.assertEqual(
            notch_class.call_args.kwargs,
            {
                "display_duration": 5,
                "window_width": 640,
                "window_height": 360,
                "display_mode": "notch",
            },
        )

    @patch("overlay_factory.NativeNotchOverlay")
    def test_unknown_mode_fails_safe_to_glass(self, overlay_class):
        create_overlay(self.spec(display_mode="unknown"))

        self.assertEqual(overlay_class.call_args.kwargs["display_mode"], "glass")


if __name__ == "__main__":
    unittest.main()
