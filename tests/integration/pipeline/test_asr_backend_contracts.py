"""Backend-neutral traces for the future unified ASR subtitle entry point.

These tests deliberately verify ordering semantics only.  Apple, Parakeet, and
MLX are allowed to emit different words and different native-final timings.
"""

import unittest

from asr_pipeline import ASREventAcceptanceGate
from tests.fixtures.asr_hypotheses import (
    apple_growth_trace,
    mlx_out_of_order_trace,
    parakeet_continuous_trace,
)


class ASRBackendProtocolContractTests(unittest.TestCase):
    def test_every_backend_trace_has_one_monotonic_entry_contract(self):
        traces = [
            apple_growth_trace(),
            parakeet_continuous_trace(),
            mlx_out_of_order_trace(),
        ]

        accepted_counts = []
        for trace in traces:
            gate = ASREventAcceptanceGate(session_generation=1)
            accepted_counts.append(sum(gate.accept(event).accepted for event in trace))

        self.assertEqual(accepted_counts, [3, 3, 2])

    def test_parakeet_without_eou_remains_an_open_stream_not_a_fake_final(self):
        trace = parakeet_continuous_trace()

        self.assertFalse(any(event.source_final for event in trace))
        self.assertEqual(len({event.stream_id for event in trace}), 1)
        self.assertEqual([event.sequence for event in trace], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
