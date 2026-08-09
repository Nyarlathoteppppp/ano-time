import unittest

from PyQt6.QtCore import QCoreApplication

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
        cls.app = QCoreApplication.instance() or QCoreApplication([])

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


if __name__ == "__main__":
    unittest.main()
