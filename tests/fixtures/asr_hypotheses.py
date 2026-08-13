"""Backend-neutral ASR traces used by subtitle-pipeline contract tests.

All text is synthetic.  Do not add classroom transcripts or user audio here.
"""

from asr_pipeline import ASRBackend, ASRHypothesis, ASRStreamBoundary, BoundaryReason


def hypothesis(
    text,
    *,
    backend=ASRBackend.APPLE,
    source_final=False,
    session_generation=1,
    stream_id=1,
    sequence=1,
    audio_anchor=10.0,
    emitted_at=10.1,
):
    return ASRHypothesis(
        text=text,
        source_final=source_final,
        backend=backend,
        session_generation=session_generation,
        stream_id=stream_id,
        sequence=sequence,
        audio_anchor=audio_anchor,
        emitted_at=emitted_at,
    )


def boundary(
    *,
    backend=ASRBackend.APPLE,
    reason=BoundaryReason.PAUSE,
    session_generation=1,
    stream_id=1,
    sequence=1,
    audio_anchor=10.0,
    emitted_at=10.1,
):
    return ASRStreamBoundary(
        backend=backend,
        session_generation=session_generation,
        stream_id=stream_id,
        sequence=sequence,
        reason=reason,
        audio_anchor=audio_anchor,
        emitted_at=emitted_at,
    )


def apple_growth_trace():
    return [
        hypothesis("A heuristic", sequence=1),
        hypothesis("A heuristic estimates", sequence=2),
        hypothesis(
            "A heuristic estimates remaining cost.",
            source_final=True,
            sequence=3,
        ),
    ]


def parakeet_continuous_trace():
    return [
        hypothesis("A heuristic", backend=ASRBackend.PARAKEET_EOU, sequence=1),
        hypothesis(
            "A heuristic estimates remaining cost to a goal",
            backend=ASRBackend.PARAKEET_EOU,
            sequence=2,
        ),
        hypothesis(
            "A heuristic estimates remaining cost to a goal and can be admissible",
            backend=ASRBackend.PARAKEET_EOU,
            sequence=3,
        ),
    ]


def mlx_out_of_order_trace():
    return [
        hypothesis("The model can predict", backend=ASRBackend.MLX, sequence=11),
        hypothesis(
            "The model can predict future values",
            backend=ASRBackend.MLX,
            sequence=12,
        ),
        hypothesis("The model can predict", backend=ASRBackend.MLX, sequence=11),
    ]
