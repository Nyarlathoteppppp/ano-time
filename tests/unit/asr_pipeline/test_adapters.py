import unittest

from asr_pipeline import ASRBackend, BoundaryReason, StreamingASRAdapter


class StreamingASRAdapterTests(unittest.TestCase):
    def test_partial_then_final_uses_increasing_sequence_and_new_stream_after_final(self):
        events = []
        adapter = StreamingASRAdapter(
            backend=ASRBackend.APPLE,
            session_generation=7,
            emit=events.append,
            clock=lambda: 12.5,
        )

        marker = adapter.note_audio_activity()
        adapter.result("A heuristic", False)
        adapter.result("A heuristic estimates cost.", True)
        adapter.note_audio_activity(20.0)
        adapter.result("A second sentence", False, emitted_at=20.2)

        self.assertEqual(marker, (1, 12.5))
        self.assertEqual([(event.stream_id, event.sequence) for event in events], [(1, 1), (1, 2), (2, 1)])
        self.assertEqual([event.audio_anchor for event in events], [12.5, 12.5, 20.0])
        self.assertTrue(events[1].source_final)

    def test_boundary_is_explicit_and_resets_audio_anchor(self):
        events = []
        adapter = StreamingASRAdapter(
            backend="mlx",
            session_generation=3,
            emit=events.append,
            clock=lambda: 1.0,
        )
        adapter.note_audio_activity(4.0)
        adapter.result("old partial", False)
        adapter.boundary(BoundaryReason.PAUSE, emitted_at=5.0)
        adapter.result("new partial", False, emitted_at=6.0)

        self.assertEqual(events[1].reason, BoundaryReason.PAUSE)
        self.assertEqual(events[1].stream_id, 1)
        self.assertEqual(events[1].sequence, 2)
        self.assertEqual(events[2].stream_id, 2)
        self.assertIsNone(events[2].audio_anchor)

    def test_adapter_boundary_prevents_prior_stream_event_from_reentering_coordinator(self):
        events = []
        adapter = StreamingASRAdapter(
            backend="apple",
            session_generation=3,
            emit=events.append,
            clock=lambda: 1.0,
        )
        adapter.result("old partial", False)
        adapter.boundary(BoundaryReason.PAUSE)
        adapter.result("fresh partial", False)

        self.assertEqual([(event.stream_id, event.sequence) for event in events], [(1, 1), (1, 2), (2, 1)])


if __name__ == "__main__":
    unittest.main()
