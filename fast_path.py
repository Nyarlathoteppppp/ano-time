"""Latest-wins scheduler for latency-critical local Apple translation work."""

from concurrent.futures import ThreadPoolExecutor
import threading


class FastPath:
    """Keep one running Apple task and discard obsolete queued partials."""

    def __init__(self, segment_store, max_workers=1):
        self.segment_store = segment_store
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="anotime-fast-path",
        )
        self._lock = threading.RLock()
        self._pending = {}
        self._closed = False

    def _forget(self, future):
        with self._lock:
            self._pending.pop(future, None)

    def _cancel_queued_partials(self):
        for future, metadata in list(self._pending.items()):
            if metadata["kind"] == "partial" and not future.running():
                if future.cancel():
                    self._pending.pop(future, None)

    def submit_partial(self, segment_id, hypothesis_revision, worker, *args):
        """Replace every queued partial with the newest visible hypothesis."""
        with self._lock:
            if self._closed:
                return None
            self._cancel_queued_partials()
            future = self._executor.submit(worker, *args)
            self._pending[future] = {
                "kind": "partial",
                "segment_id": int(segment_id),
                "hypothesis_revision": int(hypothesis_revision),
            }
        future.add_done_callback(self._forget)
        return future

    def submit_final(self, segment_id, worker, *args):
        """Invalidate partial results and place final Apple work next in line."""
        with self._lock:
            if self._closed:
                return None
            self.segment_store.invalidate_partial(segment_id)
            self._cancel_queued_partials()
            future = self._executor.submit(worker, *args)
            self._pending[future] = {
                "kind": "final",
                "segment_id": int(segment_id),
            }
        future.add_done_callback(self._forget)
        return future

    def invalidate_all(self):
        with self._lock:
            self.segment_store.invalidate_all_partials()
            for future in list(self._pending):
                if not future.running() and future.cancel():
                    self._pending.pop(future, None)

    def shutdown(self, wait=False):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for future in list(self._pending):
                if not future.running():
                    future.cancel()
            self._pending.clear()
        self._executor.shutdown(wait=wait, cancel_futures=True)
