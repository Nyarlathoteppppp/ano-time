import unittest
from types import SimpleNamespace

from api_benchmark import BENCHMARK_SENTENCES, run_translation_benchmark
from api_test_controller import ApiTestController


class _FakeTranslator:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def translate(self, text, **kwargs):
        self.calls.append((text, kwargs))
        if self.fail_at == len(self.calls):
            raise TimeoutError("test deadline")
        kwargs["on_update"]("部分")
        return f"译文 {len(self.calls)}"


class ApiBenchmarkTests(unittest.TestCase):
    def test_runs_exactly_five_isolated_fixed_requests(self):
        translator = _FakeTranslator()
        seen = []
        summary = run_translation_benchmark(translator, progress=seen.append)

        self.assertEqual(len(translator.calls), 5)
        self.assertEqual(
            tuple(text for text, _kwargs in translator.calls), BENCHMARK_SENTENCES
        )
        self.assertTrue(all(not kwargs["use_context"] for _, kwargs in translator.calls))
        self.assertTrue(
            all(not kwargs["remember_context"] for _, kwargs in translator.calls)
        )
        self.assertEqual(len(summary.successes), 5)
        self.assertEqual(len(seen), 5)

    def test_one_failure_is_reported_without_stopping_remaining_samples(self):
        translator = _FakeTranslator(fail_at=2)
        summary = run_translation_benchmark(translator)

        self.assertEqual(len(translator.calls), 5)
        self.assertEqual(len(summary.successes), 4)
        self.assertIn("TimeoutError", summary.samples[1].error)

    def test_summary_labels_total_latency_as_per_request_average(self):
        class Results:
            text = ""

            def append(self, value):
                self.text += value

        results = Results()
        controller = ApiTestController(
            SimpleNamespace(api_test_results=results)
        )
        controller._completed(5, 420.0, 810.0)

        self.assertIn("平均单次总耗时 810 ms", results.text)


if __name__ == "__main__":
    unittest.main()
