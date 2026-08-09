import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from native_notch_overlay import NativeNotchOverlay


class RecordingNotchOverlay(NativeNotchOverlay):
    def __init__(self):
        super().__init__()
        self.sent = []

    def _send(self, payload):
        self.sent.append(payload)


class NativeNotchOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mascot_is_fixed_to_expanded_notch_top_right(self):
        source = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "native_notch",
            "Sources",
            "RealtimeNotchHelper",
            "main.swift",
        )
        with open(source, encoding="utf-8") as handle:
            swift = handle.read()
        self.assertIn("ZStack(alignment: .topTrailing)", swift)
        self.assertIn(".padding(.trailing, 8)", swift)
        self.assertNotIn(".padding(.leading, 8)", swift)

    def test_scrolled_out_update_is_saved_without_redrawing_notch(self):
        overlay = RecordingNotchOverlay()
        for chunk_id in range(1, 5):
            overlay.update_text(chunk_id, f"sentence {chunk_id}", f"translation {chunk_id}")
        sent_before = len(overlay.sent)
        overlay.update_text(1, "sentence 1", "late refined translation", "final")
        self.assertEqual(len(overlay.sent), sent_before)
        self.assertEqual(
            overlay.transcript_data[1]["translated"], "late refined translation"
        )

    def test_notch_pipe_keeps_only_latest_pending_frame(self):
        class Stdin:
            pass

        class Process:
            stdin = Stdin()

            @staticmethod
            def poll():
                return None

        overlay = NativeNotchOverlay()
        overlay.process = Process()
        overlay._send({"items": [{"id": 1}]})
        overlay._send({"items": [{"id": 2}]})
        payload = json.loads(overlay._write_queue.get_nowait().decode("utf-8"))
        self.assertEqual(payload["items"][0]["id"], 2)

    def test_long_translation_is_split_for_display_not_transcript_semantics(self):
        overlay = RecordingNotchOverlay()
        translation = "这是一个用于验证显示层切分不会改变翻译语义对象的很长技术课程翻译。" * 5
        overlay.update_text(7, "A complete semantic sentence.", translation, "final")
        rendered = overlay._latest_items()
        self.assertEqual(list(overlay.transcript_data), [7])
        self.assertEqual(overlay.transcript_data[7]["translated"], translation)
        self.assertGreater(len(rendered), 1)

    def test_pause_resume_and_quit_events_follow_native_protocol(self):
        overlay = RecordingNotchOverlay()
        paused = []
        stopped = []
        overlay.pause_requested.connect(paused.append)
        overlay.stop_requested.connect(lambda: stopped.append(True))

        overlay._handle_event("pause")
        self.app.processEvents()
        self.assertTrue(overlay._paused)
        self.assertEqual(paused, [True])

        overlay._handle_event("resume")
        self.app.processEvents()
        self.assertFalse(overlay._paused)
        self.assertEqual(paused, [True, False])

        overlay._handle_event("exit")
        self.app.processEvents()
        self.assertEqual(stopped, [True])


if __name__ == "__main__":
    unittest.main()
