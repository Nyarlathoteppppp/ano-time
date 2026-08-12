import unittest

from subtitle_record_store import SubtitleRecordStore


class SubtitleRecordStoreTests(unittest.TestCase):
    def test_updates_one_complete_record_per_segment(self):
        store = SubtitleRecordStore()
        store.update(7, "A long semantic sentence", "苹果草稿", "partial")
        store.update(7, "A long semantic sentence.", "完整的最终翻译", "final")

        self.assertEqual(list(store.snapshot()), [7])
        self.assertEqual(store.get(7)["original"], "A long semantic sentence.")
        self.assertEqual(store.get(7)["translated"], "完整的最终翻译")
        self.assertTrue(store.get(7)["finalized"])

    def test_partial_cannot_regress_a_finalized_record(self):
        store = SubtitleRecordStore()
        store.update(3, "final source", "最终翻译", "final")

        self.assertIsNone(store.update(3, "old partial", "旧草稿", "partial"))
        self.assertEqual(store.get(3)["original"], "final source")
        self.assertEqual(store.get(3)["translated"], "最终翻译")

    def test_snapshots_cannot_mutate_internal_records(self):
        store = SubtitleRecordStore()
        store.update(1, "source", "translation", "partial")
        snapshot = store.snapshot()
        snapshot[1]["translated"] = "display fragment"

        self.assertEqual(store.get(1)["translated"], "translation")

    def test_latest_items_bounds_notch_projection_work(self):
        store = SubtitleRecordStore()
        for segment_id in range(1, 8):
            store.update(segment_id, f"source {segment_id}", f"translation {segment_id}")

        self.assertEqual(
            [segment_id for segment_id, _record in store.latest_items(3)],
            [5, 6, 7],
        )

    def test_latest_projection_keeps_order_without_resorting_full_history(self):
        store = SubtitleRecordStore()
        for segment_id in (4, 1, 3, 2, 5):
            store.update(segment_id, f"source {segment_id}", "translation")

        self.assertEqual(
            [segment_id for segment_id, _record in store.sorted_items()],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(
            [segment_id for segment_id, _record in store.latest_items(2)],
            [4, 5],
        )

    def test_latest_projection_can_skip_notch_only_hidden_fragments(self):
        store = SubtitleRecordStore()
        for segment_id in range(1, 7):
            store.update(segment_id, f"source {segment_id}", "translation")

        self.assertEqual(
            [
                segment_id
                for segment_id, _record in store.latest_items_excluding(3, {5})
            ],
            [3, 4, 6],
        )

    def test_committed_prefix_metadata_is_clamped_and_preserved(self):
        store = SubtitleRecordStore()
        store.update(9, "source", "稳定前缀变化尾部", "partial", 4)

        self.assertEqual(store.get(9)["committed_prefix_length"], 4)
        store.update(9, "source", "最终", "final", 100)
        self.assertEqual(store.get(9)["committed_prefix_length"], 2)


if __name__ == "__main__":
    unittest.main()
