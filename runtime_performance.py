"""Low-overhead process telemetry for diagnosing interactive regressions."""

import os
import resource
import sys
import threading
import time

from runtime_log import diagnostics_enabled, log_stage


class RuntimePerformanceSampler:
    def __init__(self, event_count_provider=None, interval_seconds=2.0):
        self.event_count_provider = event_count_provider or (lambda: 0)
        self.interval_seconds = float(interval_seconds)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not diagnostics_enabled():
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="runtime-performance-sampler",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=0.25)
        self._thread = None

    @staticmethod
    def _rss_mb():
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return rss / divisor

    def _run(self):
        previous_wall = time.monotonic()
        previous_cpu = time.process_time()
        while not self._stop.wait(self.interval_seconds):
            now_wall = time.monotonic()
            now_cpu = time.process_time()
            wall_delta = max(0.001, now_wall - previous_wall)
            cpu_percent = 100.0 * (now_cpu - previous_cpu) / wall_delta
            event_count = self.event_count_provider()
            log_stage(
                "runtime_performance",
                cpu_percent=f"{cpu_percent:.1f}",
                rss_mb=f"{self._rss_mb():.1f}",
                subtitle_events=event_count,
                subtitle_events_per_second=f"{event_count / wall_delta:.2f}",
                threads=threading.active_count(),
                pid=os.getpid(),
            )
            previous_wall = now_wall
            previous_cpu = now_cpu
