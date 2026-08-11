import unittest
import threading

from translation_workflows.single_streaming import SingleModelStreamingAdapter


class _FakeTranslator:
    def __init__(self, fail_stream=False):
        self.fail_stream = fail_stream
        self.calls = []

    def translate(self, _text, **kwargs):
        self.calls.append(dict(kwargs))
        if self.fail_stream and kwargs.get("on_update") is not None:
            raise RuntimeError("Streaming is not supported for this model")
        return "译文"


class SingleModelStreamingTests(unittest.TestCase):
    def test_auto_retries_once_without_stream_and_remembers_capability(self):
        translator = _FakeTranslator(fail_stream=True)
        adapter = SingleModelStreamingAdapter(translator, "auto")

        self.assertEqual(adapter.translate("one", on_update=lambda _text: None), "译文")
        self.assertEqual(adapter.translate("two", on_update=lambda _text: None), "译文")

        self.assertEqual(len(translator.calls), 3)
        self.assertIsNotNone(translator.calls[0].get("on_update"))
        self.assertNotIn("on_update", translator.calls[1])
        self.assertNotIn("on_update", translator.calls[2])

    def test_auto_does_not_retry_unrelated_errors(self):
        class BrokenTranslator:
            calls = 0

            def translate(self, _text, **_kwargs):
                self.calls += 1
                raise RuntimeError("Incorrect API key")

        translator = BrokenTranslator()
        adapter = SingleModelStreamingAdapter(translator, "auto")
        with self.assertRaisesRegex(RuntimeError, "Incorrect API key"):
            adapter.translate("one", on_update=lambda _text: None)
        self.assertEqual(translator.calls, 1)

    def test_off_never_requests_streaming(self):
        translator = _FakeTranslator()
        adapter = SingleModelStreamingAdapter(translator, "off")
        adapter.translate("one", on_update=lambda _text: None)
        self.assertNotIn("on_update", translator.calls[0])

    def test_concurrent_auto_calls_do_not_duplicate_capability_probe(self):
        probe_started = threading.Event()
        release_probe = threading.Event()

        class BlockingTranslator(_FakeTranslator):
            def translate(self, _text, **kwargs):
                self.calls.append(dict(kwargs))
                if kwargs.get("on_update") is not None:
                    probe_started.set()
                    release_probe.wait(1.0)
                    raise RuntimeError("Streaming is not supported for this model")
                return "译文"

        translator = BlockingTranslator()
        adapter = SingleModelStreamingAdapter(translator, "auto")
        first_result = []
        first = threading.Thread(
            target=lambda: first_result.append(
                adapter.translate("one", on_update=lambda _text: None)
            )
        )
        first.start()
        self.assertTrue(probe_started.wait(1.0))

        second = adapter.translate("two", on_update=lambda _text: None)
        release_probe.set()
        first.join(1.0)

        self.assertEqual(first_result, ["译文"])
        self.assertEqual(second, "译文")
        streaming_calls = [
            call for call in translator.calls if call.get("on_update") is not None
        ]
        self.assertEqual(len(streaming_calls), 1)
        self.assertEqual(len(translator.calls), 3)
