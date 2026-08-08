import unittest

from groq_bridge import GroqBridgeGate


class GroqBridgeGateTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.gate = GroqBridgeGate(
            max_per_minute=15,
            duplicate_window=30,
            clock=lambda: self.now,
        )

    def test_filters_short_numeric_and_filler_segments(self):
        self.assertFalse(self.gate.allow("For example now")[0])
        self.assertFalse(self.gate.allow("1234 5678 90 12")[0])
        self.assertFalse(self.gate.allow("Okay then")[0])
        self.assertFalse(self.gate.allow("You know what I mean")[0])

    def test_normalized_duplicates_recover_after_window(self):
        text = "A heuristic never overestimates the actual cost."
        self.assertTrue(self.gate.allow(text)[0])
        self.assertFalse(self.gate.allow("A HEURISTIC never overestimates the actual cost!")[0])
        self.now += 30
        self.assertTrue(self.gate.allow(text)[0])

    def test_soft_budget_recovers_after_one_minute(self):
        for index in range(15):
            self.assertTrue(
                self.gate.allow(f"This is useful technical sentence number {index}")[0]
            )
        self.assertFalse(self.gate.allow("This sentence exceeds the current soft budget")[0])
        self.now += 60
        self.assertTrue(self.gate.allow("This sentence is accepted after budget recovery")[0])


if __name__ == "__main__":
    unittest.main()
