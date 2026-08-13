"""Contracts for the MLX rolling-buffer adapter boundary.

These tests use no model, microphone, Qt event loop or remote provider.  They
verify only that the established rolling audio/VAD loop now delivers ordered
ASR events to the shared Coordinator instead of resurrecting the former direct
subtitle path.
"""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from asr_pipeline import ASRBackend
from main import Pipeline
from tests.support.recorders import RecordingSignal


class _InlineExecutor:
    """Make the serial MLX worker deterministic for this transport contract."""

    def __init__(self, *args, **kwargs):
        pass

    def submit(self, callback, *args, **kwargs):
        callback(*args, **kwargs)
        return SimpleNamespace()

    def shutdown(self, **kwargs):
        pass


class _FakeAudio:
    sample_rate = 100
    silence_threshold = 0.01
    max_phrase_duration = 0.9

    def generator(self):
        # First rolling snapshot becomes a partial; the second passes the hard
        # phrase limit and becomes a VAD-final snapshot.
        yield np.full(60, 0.1, dtype=np.float32)
        yield np.full(60, 0.1, dtype=np.float32)


class _FakeCoordinator:
    def __init__(self):
        self.events = []

    def accept(self, event):
        self.events.append(event)
        return SimpleNamespace(accepted=True)


class _FakeRuntime:
    def __init__(self):
        self.coordinator = _FakeCoordinator()
        self.fast_path = None
        self.preview_service = None
        self.shutdown_called = False

    def shutdown(self):
        self.shutdown_called = True


class MLXRollingContractTests(unittest.TestCase):
    def _pipeline(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.running = True
        pipeline._paused = threading.Event()
        pipeline._asr_session_generation = 9
        pipeline._pause_boundary_handler = None
        pipeline._fast_path = None
        pipeline._preview_service = None
        pipeline.last_final_text = ""
        pipeline.audio = _FakeAudio()
        results = iter(["A rolling partial", "A completed MLX sentence."])
        pipeline.transcriber = SimpleNamespace(
            transcribe=lambda *_args, **_kwargs: next(results)
        )
        pipeline.signals = SimpleNamespace(
            runtime_status=RecordingSignal(),
            pipeline_error=RecordingSignal(),
        )
        pipeline._session_settings = lambda: SimpleNamespace(
            update_interval=-1.0,
            silence_threshold=0.01,
            silence_duration=0.4,
        )
        pipeline._process_partial_chunk = lambda *_args: self.fail(
            "MLX must not use the legacy partial subtitle path"
        )
        pipeline._process_final_chunk = lambda *_args: self.fail(
            "MLX must not use the legacy final subtitle path"
        )
        return pipeline

    def test_mlx_partial_and_vad_final_enter_shared_coordinator(self):
        pipeline = self._pipeline()
        runtime = _FakeRuntime()
        pipeline._create_shared_asr_runtime = lambda **_kwargs: runtime

        with patch("main.ThreadPoolExecutor", _InlineExecutor):
            pipeline._processing_loop_mlx()

        events = runtime.coordinator.events
        self.assertEqual(len(events), 2)
        self.assertEqual([event.backend for event in events], [ASRBackend.MLX] * 2)
        self.assertEqual([(event.stream_id, event.sequence) for event in events], [(1, 1), (1, 2)])
        self.assertEqual([event.source_final for event in events], [False, True])
        self.assertTrue(runtime.shutdown_called)

    def test_dispatches_mlx_to_the_dedicated_rolling_adapter_path(self):
        pipeline = Pipeline.__new__(Pipeline)
        pipeline._session_settings = lambda: SimpleNamespace(asr_backend="mlx")
        called = []
        pipeline._processing_loop_mlx = lambda: called.append("mlx")

        pipeline.processing_loop()

        self.assertEqual(called, ["mlx"])


if __name__ == "__main__":
    unittest.main()
