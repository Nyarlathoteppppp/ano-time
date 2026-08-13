import unittest

from asr_pipeline import (
    ASRBackend,
    ASREventAcceptanceGate,
    BoundaryReason,
    RollingASRAdapter,
    StreamingASRAdapter,
)


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


class RollingASRAdapterTests(unittest.TestCase):
    def test_reserve_assigns_sequence_before_completion(self):
        events = []
        adapter = RollingASRAdapter(
            session_generation=2,
            emit=events.append,
            clock=lambda: 10.0,
        )

        adapter.note_audio_activity(8.0)
        first = adapter.reserve(source_final=False)
        second = adapter.reserve(source_final=False)
        adapter.complete(second, "newer result", emitted_at=10.2)
        adapter.complete(first, "older result", emitted_at=10.3)

        gate = ASREventAcceptanceGate(session_generation=2)
        accepted = [gate.accept(event).accepted for event in events]
        self.assertEqual([(event.stream_id, event.sequence) for event in events], [(1, 2), (1, 1)])
        self.assertEqual(accepted, [True, False])
        self.assertEqual(events[0].audio_anchor, 8.0)

    def test_vad_final_opens_new_capture_stream_before_next_partial(self):
        events = []
        adapter = RollingASRAdapter(
            session_generation=2,
            emit=events.append,
            clock=lambda: 1.0,
        )

        adapter.note_audio_activity(1.0)
        final = adapter.reserve(source_final=True)
        adapter.note_audio_activity(2.0)
        next_partial = adapter.reserve(source_final=False)
        adapter.complete(final, "First completed phrase", emitted_at=3.0)
        adapter.complete(next_partial, "Second phrase", emitted_at=3.2)

        self.assertEqual((final.stream_id, next_partial.stream_id), (1, 2))
        self.assertTrue(events[0].source_final)
        self.assertEqual([event.stream_id for event in events], [1, 2])
        self.assertEqual([event.audio_anchor for event in events], [1.0, 2.0])

    def test_pause_boundary_seals_visible_stream_and_drops_queued_results(self):
        events = []
        gate = ASREventAcceptanceGate(session_generation=2)

        def emit(event):
            events.append(event)
            return gate.accept(event)

        adapter = RollingASRAdapter(
            session_generation=2,
            emit=emit,
            clock=lambda: 1.0,
        )

        old = adapter.reserve(source_final=False)
        adapter.complete(old, "Visible old phrase", emitted_at=1.1)
        queued_final = adapter.reserve(source_final=True)
        boundary = adapter.boundary(BoundaryReason.PAUSE, emitted_at=1.2)
        stale = adapter.complete(queued_final, "Must not return", emitted_at=1.3)
        fresh = adapter.reserve(source_final=False)
        adapter.complete(fresh, "Fresh phrase", emitted_at=1.4)

        self.assertTrue(boundary.accepted)
        self.assertIsNone(stale)
        self.assertEqual([(event.stream_id, event.sequence) for event in events], [(1, 1), (1, 3), (3, 1)])
        self.assertEqual(events[1].reason, BoundaryReason.PAUSE)

    def test_completed_vad_final_is_not_sealed_again_by_pause(self):
        events = []
        gate = ASREventAcceptanceGate(session_generation=2)

        def emit(event):
            events.append(event)
            return gate.accept(event)

        adapter = RollingASRAdapter(
            session_generation=2,
            emit=emit,
            clock=lambda: 1.0,
        )

        final = adapter.reserve(source_final=True)
        adapter.complete(final, "Completed sentence", emitted_at=1.1)
        boundary = adapter.boundary(BoundaryReason.PAUSE, emitted_at=1.2)

        self.assertIsNone(boundary)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].source_final)


if __name__ == "__main__":
    unittest.main()
