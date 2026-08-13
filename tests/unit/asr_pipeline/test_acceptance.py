import unittest

from asr_pipeline import ASRBackend, ASREventAcceptanceGate
from tests.fixtures.asr_hypotheses import boundary, hypothesis, mlx_out_of_order_trace


class ASREventAcceptanceGateTests(unittest.TestCase):
    def test_accepts_monotonic_apple_trace(self):
        gate = ASREventAcceptanceGate(session_generation=1)
        events = [
            hypothesis("A heuristic", sequence=1),
            hypothesis("A heuristic estimates", sequence=2),
            hypothesis("A heuristic estimates cost.", source_final=True, sequence=3),
        ]

        self.assertEqual([gate.accept(event).reason for event in events], ["accepted"] * 3)
        self.assertEqual(gate.active_stream_id, 1)

    def test_rejects_late_mlx_buffer_after_newer_snapshot(self):
        gate = ASREventAcceptanceGate(session_generation=1)
        decisions = [gate.accept(event) for event in mlx_out_of_order_trace()]

        self.assertEqual([item.accepted for item in decisions], [True, True, False])
        self.assertEqual(decisions[-1].reason, "stale_sequence")

    def test_new_stream_supersedes_late_result_from_previous_stream(self):
        gate = ASREventAcceptanceGate(session_generation=1)
        self.assertTrue(gate.accept(hypothesis("old stream", stream_id=5, sequence=1)).accepted)
        self.assertTrue(gate.accept(boundary(stream_id=5, sequence=2)).accepted)
        self.assertTrue(gate.accept(hypothesis("new stream", stream_id=6, sequence=1)).accepted)

        late = gate.accept(hypothesis("old stream late", stream_id=5, sequence=3))
        self.assertFalse(late.accepted)
        self.assertEqual(late.reason, "stale_stream")

    def test_rejects_callback_from_previous_session_after_pause_or_relaunch(self):
        gate = ASREventAcceptanceGate(session_generation=8)
        stale = hypothesis(
            "previous lecture callback",
            backend=ASRBackend.MLX,
            session_generation=7,
            sequence=100,
        )

        decision = gate.accept(stale)

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "stale_session")

    def test_reset_clears_old_stream_state_for_new_session(self):
        gate = ASREventAcceptanceGate(session_generation=1)
        self.assertTrue(gate.accept(hypothesis("first", stream_id=9, sequence=10)).accepted)
        gate.reset(2)

        accepted = gate.accept(
            hypothesis("new session", session_generation=2, stream_id=1, sequence=1)
        )

        self.assertTrue(accepted.accepted)
        self.assertEqual(gate.active_stream_id, 1)


if __name__ == "__main__":
    unittest.main()
