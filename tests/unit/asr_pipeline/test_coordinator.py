import unittest

from asr_pipeline import (
    ASRBackend,
    ASRSubtitleCoordinator,
    ASRStreamBoundary,
    BoundaryReason,
)
from tests.fixtures.asr_hypotheses import hypothesis


class ASRSubtitleCoordinatorTests(unittest.TestCase):
    def _coordinator(self, **overrides):
        self.firsts = []
        self.stable = []
        self.partials = []
        self.finals = []
        self.boundaries = []
        self.idles = 0
        options = dict(
            session_generation=1,
            stable_prefix_window=0.0,
            stable_prefix_min_words=1,
            on_first_partial=self.firsts.append,
            on_stable_prefix=self.stable.append,
            on_partial=self.partials.append,
            on_semantic_final=self.finals.append,
            on_source_idle=self._on_idle,
            on_boundary=self.boundaries.append,
        )
        options.update(overrides)
        return ASRSubtitleCoordinator(**options)

    def _on_idle(self):
        self.idles += 1

    def test_apple_growth_keeps_one_partial_segment_until_native_final(self):
        coordinator = self._coordinator()
        coordinator.accept(hypothesis("A heuristic", sequence=1, emitted_at=1.0))
        coordinator.accept(hypothesis("A heuristic estimates cost", sequence=2, emitted_at=1.5))
        coordinator.accept(hypothesis(
            "A heuristic estimates cost.",
            source_final=True,
            sequence=3,
            emitted_at=2.0,
        ))

        self.assertEqual([item.segment_id for item in self.partials], [1, 1])
        self.assertEqual(self.partials[-1].text, "A heuristic estimates cost")
        self.assertEqual(self.partials[-1].observed_at, 1.5)
        self.assertEqual([(item.segment_id, item.text) for item in self.finals], [(1, "A heuristic estimates cost.")])
        self.assertEqual(self.idles, 1)

    def test_stale_mlx_result_cannot_rewrite_current_partial(self):
        coordinator = self._coordinator()
        coordinator.accept(hypothesis(
            "The model can predict", backend=ASRBackend.MLX, sequence=10, emitted_at=1.0
        ))
        coordinator.accept(hypothesis(
            "The model can predict future values", backend=ASRBackend.MLX, sequence=11, emitted_at=2.0
        ))
        stale = coordinator.accept(hypothesis(
            "The model can predict", backend=ASRBackend.MLX, sequence=10, emitted_at=3.0
        ))

        self.assertFalse(stale.accepted)
        self.assertEqual(self.partials[-1].text, "The model can predict future values")

    def test_parakeet_without_eou_stays_provisional_and_creates_no_fake_final(self):
        coordinator = self._coordinator()
        coordinator.accept(hypothesis(
            "A heuristic estimates remaining cost to a goal",
            backend=ASRBackend.PARAKEET_EOU,
            sequence=1,
            emitted_at=1.0,
        ))
        coordinator.accept(hypothesis(
            "A heuristic estimates remaining cost to a goal and can be admissible",
            backend=ASRBackend.PARAKEET_EOU,
            sequence=2,
            emitted_at=2.0,
        ))

        self.assertEqual(self.finals, [])
        self.assertEqual(self.partials[-1].segment_id, 1)

    def test_parakeet_host_policy_commits_only_stable_discourse_boundary(self):
        coordinator = self._coordinator(host_semantic_boundaries=True)
        coordinator.accept(hypothesis(
            "The compressed representation preserves the important structure "
            "of the original data but the decoder needs additional information",
            backend=ASRBackend.PARAKEET_EOU,
            sequence=1,
            emitted_at=1.0,
        ))
        coordinator.accept(hypothesis(
            "The compressed representation preserves the important structure "
            "of the original data but the decoder needs additional information "
            "for reliable reconstruction",
            backend=ASRBackend.PARAKEET_EOU,
            sequence=2,
            emitted_at=1.5,
        ))

        self.assertEqual(
            [(item.segment_id, item.text, item.cut_reason) for item in self.finals],
            [(
                1,
                "The compressed representation preserves the important structure of the original data",
                "host_discourse_boundary",
            )],
        )
        self.assertEqual(self.partials[-1].segment_id, 2)
        self.assertTrue(self.partials[-1].text.startswith("but the decoder"))

    def test_pause_boundary_seals_meaningful_remainder_without_fake_remote_final(self):
        coordinator = self._coordinator()
        coordinator.accept(hypothesis("A meaningful unfinished phrase", sequence=1, emitted_at=1.0))
        coordinator.accept(ASRStreamBoundary(
            backend=ASRBackend.APPLE,
            session_generation=1,
            stream_id=1,
            sequence=2,
            reason=BoundaryReason.PAUSE,
            audio_anchor=1.0,
            emitted_at=2.0,
        ))

        self.assertEqual(self.finals, [])
        self.assertEqual(len(self.boundaries), 1)
        self.assertEqual(self.boundaries[0].segment_id, 1)
        self.assertEqual(self.boundaries[0].text, "A meaningful unfinished phrase")

    def test_new_stream_cannot_inherit_prior_remainder_after_pause(self):
        coordinator = self._coordinator()
        coordinator.accept(hypothesis("Old unfinished phrase", sequence=1, emitted_at=1.0))
        coordinator.accept(ASRStreamBoundary(
            backend=ASRBackend.APPLE,
            session_generation=1,
            stream_id=1,
            sequence=2,
            reason=BoundaryReason.PAUSE,
            audio_anchor=1.0,
            emitted_at=2.0,
        ))
        coordinator.accept(hypothesis("Fresh sentence", stream_id=2, sequence=1, emitted_at=3.0))

        self.assertEqual(self.partials[-1].segment_id, 2)
        self.assertEqual(self.partials[-1].text, "Fresh sentence")


if __name__ == "__main__":
    unittest.main()
