import unittest

from global_shortcut import (
    DoubleModifierDetector,
    MacCarbonHotkeyShortcut,
    accessibility_trusted,
)


class DoubleModifierDetectorTests(unittest.TestCase):
    def test_accessibility_probe_returns_bool(self):
        self.assertIsInstance(accessibility_trusted(), bool)

    def test_native_hotkey_uses_control_s(self):
        self.assertEqual(MacCarbonHotkeyShortcut._KEY_CODE_S, 1)
        self.assertEqual(MacCarbonHotkeyShortcut._CONTROL_KEY, 1 << 12)

    def test_two_clean_option_presses_activate(self):
        detector = DoubleModifierDetector(interval_seconds=0.32)
        self.assertFalse(detector.modifier_changed(True, now=1.00))
        self.assertFalse(detector.modifier_changed(False, now=1.05))
        self.assertFalse(detector.modifier_changed(True, now=1.20))
        self.assertTrue(detector.modifier_changed(False, now=1.25))

    def test_slow_second_press_does_not_activate(self):
        detector = DoubleModifierDetector(interval_seconds=0.30)
        detector.modifier_changed(True, now=1.00)
        detector.modifier_changed(False, now=1.05)
        detector.modifier_changed(True, now=1.50)
        self.assertFalse(detector.modifier_changed(False, now=1.55))

    def test_option_combination_with_other_key_is_ignored(self):
        detector = DoubleModifierDetector(interval_seconds=0.32)
        detector.modifier_changed(True, now=1.00)
        detector.key_down()
        detector.modifier_changed(False, now=1.05)
        detector.modifier_changed(True, now=1.15)
        self.assertFalse(detector.modifier_changed(False, now=1.20))

    def test_other_modifier_cancels_press(self):
        detector = DoubleModifierDetector(interval_seconds=0.32)
        detector.modifier_changed(True, now=1.00)
        detector.modifier_changed(True, other_modifiers=True, now=1.02)
        detector.modifier_changed(False, now=1.05)
        detector.modifier_changed(True, now=1.15)
        self.assertFalse(detector.modifier_changed(False, now=1.20))

    def test_cooldown_prevents_repeated_activation(self):
        detector = DoubleModifierDetector(interval_seconds=0.32, cooldown_seconds=0.6)
        for now in (1.00, 1.05, 1.15):
            detector.modifier_changed(now != 1.05, now=now)
        self.assertTrue(detector.modifier_changed(False, now=1.20))
        detector.modifier_changed(True, now=1.30)
        detector.modifier_changed(False, now=1.35)
        detector.modifier_changed(True, now=1.45)
        self.assertFalse(detector.modifier_changed(False, now=1.50))

    def test_default_ui_interval_accepts_a_relaxed_double_tap(self):
        detector = DoubleModifierDetector(interval_seconds=0.45)
        detector.modifier_changed(True, now=1.00)
        detector.modifier_changed(False, now=1.05)
        detector.modifier_changed(True, now=1.42)
        self.assertTrue(detector.modifier_changed(False, now=1.47))


if __name__ == "__main__":
    unittest.main()
