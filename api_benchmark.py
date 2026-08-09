"""Small, deterministic translation benchmark used by the control center."""

from dataclasses import dataclass
import statistics
import time


BENCHMARK_SENTENCES = (
    "An admissible heuristic never overestimates the true cost to the goal.",
    "Gradient descent updates the parameters in the opposite direction of the gradient.",
    "The posterior distribution is proportional to the likelihood times the prior.",
    "A Markov decision process assumes that the next state depends only on the current state and action.",
    "The eigenvalues of a covariance matrix describe the variance along its principal components.",
)


@dataclass(frozen=True)
class BenchmarkSample:
    index: int
    source: str
    translation: str
    first_token_ms: float
    total_ms: float
    error: str = ""


@dataclass(frozen=True)
class BenchmarkSummary:
    samples: tuple[BenchmarkSample, ...]

    @property
    def successes(self):
        return tuple(sample for sample in self.samples if not sample.error)

    @property
    def average_first_token_ms(self):
        values = [sample.first_token_ms for sample in self.successes]
        return statistics.fmean(values) if values else 0.0

    @property
    def average_total_ms(self):
        values = [sample.total_ms for sample in self.successes]
        return statistics.fmean(values) if values else 0.0

    @property
    def attempted(self):
        return len(self.samples)

    @property
    def stopped_early(self):
        return self.attempted < len(BENCHMARK_SENTENCES)


def is_terminal_configuration_error(exc):
    """Return true when repeating the same benchmark request cannot help."""
    status_code = getattr(exc, "status_code", None)
    if status_code in {400, 401, 403, 404}:
        return True
    if isinstance(exc, ValueError):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in (
        "invalid url",
        "unsupported protocol",
        "api key",
        "authentication",
        "unauthorized",
        "forbidden",
    ))


def run_translation_benchmark(
    translator,
    *,
    progress=None,
    should_stop=None,
    deadline_seconds=3.0,
):
    """Send five fixed requests without retaining conversational context."""
    samples = []
    for index, source in enumerate(BENCHMARK_SENTENCES, start=1):
        if should_stop and should_stop():
            break
        started = time.perf_counter()
        first_token_at = [None]

        def on_update(_partial):
            if first_token_at[0] is None:
                first_token_at[0] = time.perf_counter()

        try:
            translation = translator.translate(
                source,
                use_context=False,
                remember_context=False,
                on_update=on_update,
                deadline=time.monotonic() + deadline_seconds,
            )
            finished = time.perf_counter()
            first = first_token_at[0] or finished
            sample = BenchmarkSample(
                index=index,
                source=source,
                translation=translation,
                first_token_ms=(first - started) * 1000,
                total_ms=(finished - started) * 1000,
            )
        except Exception as exc:
            finished = time.perf_counter()
            terminal = is_terminal_configuration_error(exc)
            prefix = "Configuration error — test stopped: " if terminal else ""
            sample = BenchmarkSample(
                index=index,
                source=source,
                translation="",
                first_token_ms=0.0,
                total_ms=(finished - started) * 1000,
                error=f"{prefix}{type(exc).__name__}: {exc}",
            )
        samples.append(sample)
        if progress:
            progress(sample)
        if sample.error.startswith("Configuration error — test stopped:"):
            break
    return BenchmarkSummary(tuple(samples))
