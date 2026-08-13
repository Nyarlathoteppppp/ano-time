import unittest

from asr_pipeline import ASRBackend, ASRHypothesis, ASRStreamBoundary, BoundaryReason


class ASREventTests(unittest.TestCase):
    def test_hypothesis_normalizes_whitespace_without_mutating_semantics(self):
        event = ASRHypothesis(
            text="  A   heuristic\n estimates  cost ",
            source_final=False,
            backend="apple",
            session_generation=1,
            stream_id=2,
            sequence=3,
            audio_anchor=4,
            emitted_at=5,
        )

        self.assertEqual(event.text, "A heuristic estimates cost")
        self.assertEqual(event.backend, ASRBackend.APPLE)
        self.assertFalse(event.source_final)

    def test_hypothesis_rejects_empty_text_and_negative_ordering_fields(self):
        base = dict(
            source_final=False,
            backend=ASRBackend.MLX,
            session_generation=1,
            stream_id=2,
            sequence=3,
            audio_anchor=None,
            emitted_at=5,
        )
        with self.assertRaises(ValueError):
            ASRHypothesis(text="  ", **base)
        with self.assertRaises(ValueError):
            ASRHypothesis(text="valid", sequence=-1, **{k: v for k, v in base.items() if k != "sequence"})

    def test_boundary_is_typed_without_requiring_fake_empty_final_text(self):
        event = ASRStreamBoundary(
            backend="parakeet_eou",
            session_generation=1,
            stream_id=3,
            sequence=4,
            reason="pause",
            audio_anchor=None,
            emitted_at=8,
        )

        self.assertEqual(event.backend, ASRBackend.PARAKEET_EOU)
        self.assertEqual(event.reason, BoundaryReason.PAUSE)


if __name__ == "__main__":
    unittest.main()
