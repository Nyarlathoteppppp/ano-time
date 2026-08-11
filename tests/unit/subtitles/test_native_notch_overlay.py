import json
import os
import struct
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from native_notch_overlay import NativeNotchOverlay
from subtitle_event import SubtitleEvent, SubtitleStage
from tests.support.paths import project_path


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

    def test_mascots_are_fixed_to_both_expanded_notch_edges(self):
        source = project_path(
            "native_notch", "Sources", "RealtimeNotchHelper", "main.swift"
        )
        with source.open(encoding="utf-8") as handle:
            swift = handle.read()
        self.assertIn("ZStack(alignment: .top)", swift)
        self.assertIn("HStack(spacing: 0)", swift)
        self.assertIn("TrailingMascotAsset.image", swift)
        self.assertIn('Resources/lgcr@2x.png', swift)
        self.assertIn(".padding(.horizontal, 8)", swift)

        resource = os.path.join(
            os.path.dirname(source), "Resources", "lgcr@2x.png"
        )
        with open(resource, "rb") as handle:
            header = handle.read(24)
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", header[16:24]), (52, 52))

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

    def test_glass_transition_detaches_terminating_native_process(self):
        overlay = NativeNotchOverlay()
        process = MagicMock()
        process.wait.return_value = 0
        overlay.process = process

        with patch("native_notch_overlay.threading.Thread") as thread:
            overlay._retire_native_process()

        self.assertIsNone(overlay.process)
        thread.assert_called_once()

    def test_return_to_notch_restarts_helper_and_replays_latest_frame(self):
        overlay = RecordingNotchOverlay()
        overlay.update_text(1, "A sentence", "一句话", "final")
        overlay.sent.clear()
        delegate = MagicMock()
        overlay.delegate = delegate

        with patch.object(NativeNotchOverlay, "show") as show:
            overlay._show_native_overlay()

        delegate.close.assert_called_once()
        self.assertIsNone(overlay.delegate)
        show.assert_called_once()
        self.assertEqual(overlay._display_mode, "notch")
        self.assertEqual(overlay.sent[-1]["items"][0]["translated"], "一句话")

    def test_long_translation_is_split_for_display_not_transcript_semantics(self):
        overlay = RecordingNotchOverlay()
        translation = "这是一个用于验证显示层切分不会改变翻译语义对象的很长技术课程翻译。" * 5
        overlay.update_text(7, "A complete semantic sentence.", translation, "final")
        rendered = overlay._latest_items()
        self.assertEqual(list(overlay.transcript_data), [7])
        self.assertEqual(overlay.transcript_data[7]["translated"], translation)
        self.assertEqual(len(rendered), 1)
        self.assertGreater(len(rendered[0]["fragments"]), 1)

    def test_long_finalized_source_splits_only_at_clause_boundaries(self):
        overlay = RecordingNotchOverlay()
        first = " ".join(f"alpha{i}" for i in range(20)) + ","
        second = " ".join(f"beta{i}" for i in range(20)) + "."
        original = f"{first} {second}"
        overlay.update_text(12, original, "第一部分，第二部分。", "final")

        rendered = overlay._latest_items()
        self.assertEqual(len(rendered), 1)
        self.assertEqual(len(rendered[0]["fragments"]), 2)
        self.assertTrue(rendered[0]["fragments"][0]["original"].endswith(","))
        self.assertEqual(overlay.transcript_data[12]["original"], original)

    def test_long_final_without_safe_boundary_remains_one_semantic_record(self):
        text = " ".join(f"token{i}" for i in range(40))
        self.assertEqual(
            NativeNotchOverlay._split_finalized_source(text, 34), [text]
        )

    def test_long_provisional_translation_is_split_for_small_notch_visibility(self):
        overlay = RecordingNotchOverlay()
        translation = "正在增长的苹果实时翻译草稿会持续追加中文内容" * 7
        overlay.update_text(8, "A growing provisional sentence", translation, "partial")
        rendered = overlay._latest_items()
        fragments = rendered[0]["fragments"]
        self.assertGreater(len(fragments), 1)
        self.assertTrue(all(item["finalized"] is False for item in fragments))
        self.assertTrue(all(
            overlay._visual_width(item["translated"]) <= 58 * 16
            for item in fragments
        ))
        self.assertEqual(overlay.transcript_data[8]["translated"], translation)

    def test_mixed_width_translation_uses_rendered_capacity(self):
        text = "半正定矩阵 covariance matrix 与 posterior distribution " * 5
        parts = NativeNotchOverlay._split_display_text(text, 58)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(
            NativeNotchOverlay._visual_width(part) <= 58 * 16
            for part in parts
        ))

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

    def test_activity_snapshot_survives_latest_subtitle_frame(self):
        overlay = RecordingNotchOverlay()
        overlay.update_text(1, "A sentence", "一句话", "final")
        overlay.update_runtime_status(
            "Remote", "active", "Gemini 3.5 Flash-Lite · translating"
        )
        overlay.update_text(2, "New partial", "新草稿", "partial")

        self.assertIn(
            "Remote:Gemini 3.5 Flash-Lite", overlay._busy_stages
        )

        # Exercise the real serializer: every frame carries the full snapshot.
        class Stdin:
            pass

        class Process:
            stdin = Stdin()

            @staticmethod
            def poll():
                return None

        real = NativeNotchOverlay()
        real.process = Process()
        real._busy_stages.add("Remote:Gemini")
        real._send({"items": [{"id": 2}]})
        payload = json.loads(real._write_queue.get_nowait().decode("utf-8"))
        self.assertEqual(payload["busyStages"], ["Remote:Gemini"])

    def test_typed_event_projects_committed_target_prefix_to_native_frame(self):
        overlay = RecordingNotchOverlay()
        event = SubtitleEvent.create(
            15,
            3,
            SubtitleStage.AI_PREVIEW,
            "A heuristic estimates the remaining cost",
            "启发式函数估计剩余代价",
            committed_prefix_length=6,
        )

        overlay.update_event(event)

        item = overlay.sent[-1]["items"][0]["fragments"][0]
        self.assertEqual(item["committedPrefixLength"], 6)

    def test_crossing_display_split_threshold_keeps_semantic_identity(self):
        overlay = RecordingNotchOverlay()
        overlay.update_text(22, "source", "较短的翻译", "partial")
        before = overlay.sent[-1]["items"][0]
        overlay.update_text(22, "source", "很长的翻译内容" * 20, "partial")
        after = overlay.sent[-1]["items"][0]

        self.assertEqual(before["id"], after["id"])
        self.assertEqual(before["fragments"][0]["id"], after["fragments"][0]["id"])
        self.assertGreater(len(after["fragments"]), 1)


if __name__ == "__main__":
    unittest.main()
