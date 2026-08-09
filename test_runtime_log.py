import logging
import queue
import time
import unittest

from runtime_log import DroppingQueueHandler


class RuntimeLogTests(unittest.TestCase):
    def test_full_log_queue_never_blocks_caller(self):
        log_queue = queue.Queue(maxsize=1)
        log_queue.put_nowait("occupied")
        handler = DroppingQueueHandler(log_queue)
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "message", (), None
        )
        started = time.perf_counter()
        handler.emit(record)
        self.assertLess(time.perf_counter() - started, 0.05)
        self.assertEqual(log_queue.get_nowait(), "occupied")


if __name__ == "__main__":
    unittest.main()
