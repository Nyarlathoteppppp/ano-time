import threading
import unittest

from segment_store import SegmentStore
from subtitle_event import SubtitleStage
from translation_preview import ProgressiveTranslationPreview


class _Translator:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def translate(self, text, **kwargs):
        self.calls.append((text, kwargs))
        callback = kwargs.get("on_update")
        if callback:
            callback(self.result[: max(1, len(self.result) // 2)])
        return self.result


class ProgressiveTranslationPreviewTests(unittest.TestCase):
    def _service(self, *, bridge=None, final=None):
        store = SegmentStore()
        emitted = []
        completed = threading.Event()

        def emit(segment_id, source, translated, state, stage, **kwargs):
            event = store.publish(
                segment_id,
                stage,
                source,
                translated,
                finalized=state == "final",
                **kwargs,
            )
            if event is not None:
                emitted.append(event)
                completed.set()
            return event

        service = ProgressiveTranslationPreview(
            emit_subtitle=emit,
            segment_store=store,
            bridge_client=lambda: bridge,
            final_client=lambda: final,
            bridge_gate=type("Gate", (), {"allow": lambda _self, _text: (True, "ok")})(),
            context_snapshot=lambda: "previous finalized context",
            is_active=lambda: True,
        )
        return service, store, emitted, completed

    def test_final_model_preview_works_when_bridge_is_off(self):
        final = _Translator("模型预测目标变量")
        service, store, emitted, completed = self._service(final=final)
        source = "the model predicts our target variable now"
        try:
            store.publish(1, SubtitleStage.ASR_PARTIAL, source)
            service.observe(1, store.hypothesis_revision(1), source)
            self.assertTrue(completed.wait(0.5))
            state = store.snapshot(1)
            self.assertFalse(state.finalized)
            self.assertEqual(state.translation_stage, SubtitleStage.AI_PREVIEW)
            self.assertEqual(
                final.calls[0][1]["context_text"],
                "previous finalized context",
            )
            self.assertTrue(all(not event.finalized for event in emitted))
        finally:
            service.shutdown()

    def test_final_model_preview_first_triggers_at_five_words(self):
        final = _Translator("五词即可开始预览")
        service, store, _emitted, completed = self._service(final=final)
        source = "one two three four five"
        try:
            store.publish(10, SubtitleStage.ASR_PARTIAL, source)
            service.observe(10, store.hypothesis_revision(10), source)
            self.assertTrue(completed.wait(0.5))
            self.assertEqual(final.calls[0][0], source)
        finally:
            service.shutdown()

    def test_later_preview_receives_the_last_displayed_translation(self):
        final = _Translator("第一版中文")
        service, store, _emitted, completed = self._service(final=final)
        first = "one two three four five"
        second = "one two three four five six seven eight nine ten eleven"
        try:
            service._final_policy.minimum_interval = 0
            store.publish(11, SubtitleStage.ASR_PARTIAL, first)
            service.observe(11, store.hypothesis_revision(11), first)
            self.assertTrue(completed.wait(0.5))
            completed.clear()
            final.result = "第一版中文继续扩展"
            store.publish(11, SubtitleStage.ASR_PARTIAL, second)
            service.observe(11, store.hypothesis_revision(11), second)
            self.assertTrue(completed.wait(0.5))
            self.assertEqual(
                final.calls[-1][1]["previous_preview"],
                "第一版中文",
            )
        finally:
            service.shutdown()

    def test_optional_bridge_uses_stable_source_without_final_client(self):
        bridge = _Translator("桥接译文")
        service, store, _emitted, completed = self._service(bridge=bridge)
        source = "a stable source prefix"
        try:
            store.publish(2, SubtitleStage.ASR_PARTIAL, source)
            service.observe(
                2,
                store.hypothesis_revision(2),
                source,
                stable_source_text=source,
            )
            self.assertTrue(completed.wait(0.5))
            self.assertEqual(
                store.snapshot(2).translation_stage,
                SubtitleStage.BRIDGE_PREVIEW,
            )
        finally:
            service.shutdown()

    def test_finalize_rejects_late_preview_at_segment_store_boundary(self):
        final = _Translator("预览译文")
        service, store, _emitted, _completed = self._service(final=final)
        source = "the model predicts our target variable now"
        try:
            store.publish(3, SubtitleStage.ASR_PARTIAL, source)
            hypothesis = store.hypothesis_revision(3)
            store.publish(3, SubtitleStage.ASR_FINAL, source, finalized=True)
            service.observe(3, hypothesis, source)
            self.assertNotEqual(
                store.snapshot(3).translation_stage,
                SubtitleStage.AI_PREVIEW,
            )
        finally:
            service.shutdown()
