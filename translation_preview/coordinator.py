"""Bounded active-plus-latest-pending preview scheduler."""

from concurrent.futures import ThreadPoolExecutor
import threading
import time

from .request import PreviewRequest


class ProgressivePreviewCoordinator:
    """Keep one active request and replace only queued obsolete work."""

    def __init__(self, deadline_seconds, thread_name="translation-preview"):
        self.deadline_seconds = max(0.1, float(deadline_seconds))
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=thread_name,
        )
        self._lock = threading.RLock()
        self._generation = 0
        self._invalidated_generation = 0
        self._futures = {}
        self._closed = False

    def submit(self, segment_id, hypothesis_revision, source_text, worker):
        with self._lock:
            if self._closed:
                return None
            self._generation += 1
            generation = self._generation
            for future in list(self._futures):
                if not future.running() and future.cancel():
                    self._futures.pop(future, None)
            request = PreviewRequest(
                segment_id=int(segment_id),
                hypothesis_revision=int(hypothesis_revision),
                source_text=str(source_text),
                generation=generation,
                deadline=time.monotonic() + self.deadline_seconds,
            )
            future = self._executor.submit(worker, request)
            self._futures[future] = request
        future.add_done_callback(self._forget)
        return request

    def _forget(self, future):
        with self._lock:
            self._futures.pop(future, None)

    def is_valid(self, request):
        """An active older prefix remains useful until explicitly invalidated."""
        with self._lock:
            return (
                not self._closed
                and request.generation > self._invalidated_generation
            )

    def invalidate(self):
        with self._lock:
            self._generation += 1
            self._invalidated_generation = self._generation
            for future in list(self._futures):
                if not future.running() and future.cancel():
                    self._futures.pop(future, None)

    def shutdown(self):
        with self._lock:
            self._closed = True
            self._generation += 1
            self._invalidated_generation = self._generation
        self._executor.shutdown(wait=False, cancel_futures=True)

