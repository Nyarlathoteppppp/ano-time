import atexit
import logging
import os
import queue
import threading
import time
from logging.handlers import QueueListener, RotatingFileHandler


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_PATH = os.path.join(LOG_DIR, "runtime.log")
LOG_HISTORY_DIR = os.path.join(LOG_DIR, "history")
HISTORY_LIMIT = 5
HISTORY_MAX_AGE_DAYS = 7

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
_session_started = False
_diagnostics_enabled = False
_startup_lock = threading.Lock()


def diagnostics_enabled():
    """Return the process-wide diagnostics state without touching disk."""
    return _diagnostics_enabled


def configure_diagnostics(enabled):
    """Set the single diagnostics state used by logging and samplers."""
    global _diagnostics_enabled
    _diagnostics_enabled = bool(enabled)
    return _diagnostics_enabled


def rotate_runtime_logs(
    log_path=LOG_PATH,
    history_dir=LOG_HISTORY_DIR,
    keep=HISTORY_LIMIT,
    max_age_days=HISTORY_MAX_AGE_DAYS,
    now=None,
):
    """Archive the previous session and prune stale history."""
    now = time.time() if now is None else now
    os.makedirs(history_dir, exist_ok=True)
    if os.path.exists(log_path) and os.path.getsize(log_path):
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        destination = os.path.join(history_dir, f"runtime-{stamp}-{os.getpid()}.log")
        os.replace(log_path, destination)
    for suffix in (".1", ".2", ".3"):
        rotated = f"{log_path}{suffix}"
        if os.path.exists(rotated):
            os.remove(rotated)

    entries = sorted(
        (
            os.path.join(history_dir, name)
            for name in os.listdir(history_dir)
            if name.startswith("runtime-") and name.endswith(".log")
        ),
        key=os.path.getmtime,
        reverse=True,
    )
    oldest_allowed = now - max_age_days * 86400
    for index, path in enumerate(entries):
        if index >= keep or os.path.getmtime(path) < oldest_allowed:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


def begin_runtime_session(reset=True, enabled=None):
    """Start one opt-in non-blocking log session; safe to call repeatedly."""
    global _listener, _session_started
    if enabled is not None:
        configure_diagnostics(enabled)
    if not diagnostics_enabled():
        return False
    with _startup_lock:
        if _session_started:
            return True
        os.makedirs(LOG_DIR, exist_ok=True)
        if reset:
            rotate_runtime_logs()
        file_handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
        log_queue = queue.Queue(maxsize=2048)
        logger.addHandler(DroppingQueueHandler(log_queue))
        _listener = QueueListener(
            log_queue, file_handler, respect_handler_level=True
        )
        _listener.start()
        _session_started = True
        return True


def _stop_listener():
    if _listener is not None:
        try:
            _listener.stop()
        except queue.Full:
            pass


atexit.register(_stop_listener)


def log_stage(stage, chunk_id=None, status="ok", elapsed_ms=None, detail="", **metrics):
    if not diagnostics_enabled():
        return False
    if not _session_started:
        # Libraries and unit tests may use telemetry without launching the app.
        # Append in that case; only the confirmed primary app resets a session.
        begin_runtime_session(reset=False)
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
    return True
