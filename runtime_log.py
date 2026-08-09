import atexit
import logging
import os
import queue
from logging.handlers import QueueListener, RotatingFileHandler


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_PATH = os.path.join(LOG_DIR, "runtime.log")

os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("realtime_ton")
logger.setLevel(logging.INFO)
logger.propagate = False


class DroppingQueueHandler(logging.Handler):
    """Non-blocking logging handler for latency-sensitive callbacks."""

    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put_nowait(record)
        except queue.Full:
            # Runtime telemetry is best effort; audio and subtitles must never
            # wait for disk I/O or an overloaded logging queue.
            pass


_listener = None
if not logger.handlers:
    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    log_queue = queue.Queue(maxsize=2048)
    logger.addHandler(DroppingQueueHandler(log_queue))
    _listener = QueueListener(log_queue, file_handler, respect_handler_level=True)
    _listener.start()


def _stop_listener():
    if _listener is not None:
        try:
            _listener.stop()
        except queue.Full:
            pass


atexit.register(_stop_listener)


def log_stage(stage, chunk_id=None, status="ok", elapsed_ms=None, detail="", **metrics):
    fields = [f"stage={stage}", f"status={status}"]
    if chunk_id is not None:
        fields.append(f"chunk={chunk_id}")
    if elapsed_ms is not None:
        fields.append(f"elapsed_ms={elapsed_ms:.0f}")
    for key, value in metrics.items():
        if value is None:
            continue
        safe_key = "".join(ch for ch in str(key) if ch.isalnum() or ch == "_")
        if not safe_key:
            continue
        if isinstance(value, float):
            value = f"{value:.0f}"
        fields.append(f"{safe_key}={value}")
    if detail:
        fields.append(f"detail={detail.replace(chr(10), ' ')[:300]}")
    logger.info(" | ".join(fields))
