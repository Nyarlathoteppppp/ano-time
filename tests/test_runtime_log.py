import logging
import os
import queue
import tempfile
import time
import unittest
from unittest.mock import patch

import runtime_log
from runtime_log import (
    DroppingQueueHandler,
    configure_diagnostics,
    diagnostics_enabled,
    log_stage,
    rotate_runtime_logs,
)


class RuntimeLogTests(unittest.TestCase):
    def tearDown(self):
        configure_diagnostics(False)

    def test_diagnostics_are_off_until_explicitly_enabled(self):
        configure_diagnostics(False)
        self.assertFalse(diagnostics_enabled())
        with patch.object(runtime_log, "begin_runtime_session") as begin, patch.object(
            runtime_log.logger, "info"
        ) as info:
            self.assertFalse(log_stage("apple_partial", elapsed_ms=12))
        begin.assert_not_called()
        info.assert_not_called()

    def test_single_process_switch_enables_diagnostics(self):
        self.assertTrue(configure_diagnostics(True))
        self.assertTrue(diagnostics_enabled())

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

    def test_new_session_archives_current_log_and_prunes_history(self):
        with tempfile.TemporaryDirectory() as directory:
            current = os.path.join(directory, "runtime.log")
            history = os.path.join(directory, "history")
            os.makedirs(history)
            with open(current, "w", encoding="utf-8") as handle:
                handle.write("current session")
            now = 2_000_000_000
            os.utime(current, (now, now))
            for index in range(4):
                path = os.path.join(history, f"runtime-old-{index}.log")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(str(index))
                os.utime(path, (now - index * 60, now - index * 60))

            rotate_runtime_logs(
                log_path=current,
                history_dir=history,
                keep=2,
                max_age_days=7,
                now=now,
            )

            self.assertFalse(os.path.exists(current))
            remaining = sorted(os.listdir(history))
            self.assertEqual(len(remaining), 2)
            self.assertTrue(any(str(os.getpid()) in name for name in remaining))


if __name__ == "__main__":
    unittest.main()
