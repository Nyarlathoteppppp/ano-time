"""API token and cost accounting outside the subtitle hot path."""

import json
import os
import queue
import threading
import time
from datetime import datetime


_USAGE_KEYS = (
    "requests", "prompt_tokens", "completion_tokens", "total_tokens",
    "cost_usd", "unpriced_requests",
)


class DailyUsageLedger:
    """Keep today's totals across launches; disk writes run off the hot path."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._pending = queue.Queue()
        self._writer = None
        self._date = self._today()
        self._totals = self._empty_totals()
        self._load()

    @staticmethod
    def _today():
        return datetime.now().astimezone().date().isoformat()

    @staticmethod
    def _empty_totals():
        return {key: 0.0 if key == "cost_usd" else 0 for key in _USAGE_KEYS}

    def _roll_date_locked(self):
        today = self._today()
        if self._date != today:
            self._date = today
            self._totals = self._empty_totals()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, ValueError, TypeError):
            return
        if saved.get("date") != self._date:
            return
        totals = saved.get("totals", {})
        for key in _USAGE_KEYS:
            value = totals.get(key, 0)
            try:
                self._totals[key] = float(value) if key == "cost_usd" else int(value)
            except (TypeError, ValueError):
                self._totals[key] = 0.0 if key == "cost_usd" else 0

    def record(self, values):
        with self._lock:
            self._roll_date_locked()
            for key in _USAGE_KEYS:
                self._totals[key] += values.get(key, 0)
            payload = {"date": self._date, "totals": dict(self._totals)}
        self._enqueue_write(payload)

    def snapshot(self):
        with self._lock:
            self._roll_date_locked()
            return dict(self._totals)

    def _enqueue_write(self, payload):
        if self._writer is None:
            self._writer = threading.Thread(
                target=self._write_pending, name="daily-usage-writer", daemon=True
            )
            self._writer.start()
        self._pending.put((payload, None))

    def _write_pending(self):
        while True:
            payload, barrier = self._pending.get()
            if barrier is not None:
                barrier.set()
                continue
            # Coalesce bursts: only the newest cumulative snapshot is useful.
            while True:
                try:
                    candidate, candidate_barrier = self._pending.get_nowait()
                except queue.Empty:
                    break
                if candidate_barrier is not None:
                    # Write the latest state before acknowledging a flush.
                    barrier = candidate_barrier
                    break
                payload = candidate
            try:
                directory = os.path.dirname(self.path)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                temporary = f"{self.path}.tmp"
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                os.replace(temporary, self.path)
            except OSError:
                # Accounting must never interfere with translation.
                pass
            if barrier is not None:
                barrier.set()

    def flush(self, timeout=1.0):
        if self._writer is None:
            return
        barrier = threading.Event()
        self._pending.put((None, barrier))
        barrier.wait(timeout)


class TranslationUsageMeter:
    def __init__(self, daily_ledger=None):
        self._lock = threading.Lock()
        self._enabled = True
        self._started_at = time.monotonic()
        self._first_usage_at = None
        self._active_started_at = None
        self._active_elapsed = 0.0
        self._projection_started = False
        self._projection_cost_baseline = 0.0
        self._providers = {}
        self._daily_ledger = daily_ledger

    def reset(self):
        with self._lock:
            self._started_at = time.monotonic()
            self._first_usage_at = None
            self._active_started_at = None
            self._active_elapsed = 0.0
            self._projection_started = False
            self._projection_cost_baseline = 0.0
            self._providers.clear()

    def set_enabled(self, enabled):
        """Enable optional session accounting without changing provider quotas."""
        with self._lock:
            self._enabled = bool(enabled)
            if not self._enabled and self._active_started_at is not None:
                now = time.monotonic()
                self._active_elapsed += max(0.0, now - self._active_started_at)
                self._active_started_at = None

    def set_active(self, active):
        """Start/freeze the hourly projection clock without touching totals."""
        now = time.monotonic()
        with self._lock:
            if active and not self._enabled:
                return
            if active and self._active_started_at is None:
                if not self._projection_started:
                    self._projection_started = True
                    self._projection_cost_baseline = sum(
                        item["cost_usd"] for item in self._providers.values()
                    )
                self._active_started_at = now
            elif not active and self._active_started_at is not None:
                self._active_elapsed += max(0.0, now - self._active_started_at)
                self._active_started_at = None

    def record(
        self, provider, usage, input_price=0.0, output_price=0.0,
        pricing_known=False,
    ):
        if not isinstance(usage, dict):
            return
        prompt = max(0, int(usage.get("prompt_tokens") or 0))
        completion = max(0, int(usage.get("completion_tokens") or 0))
        total = max(0, int(usage.get("total_tokens") or prompt + completion))
        # A provider that returns only total_tokens cannot support an exact
        # input/output price calculation. Keep its tokens visible but do not
        # invent a cost split.
        has_split = bool(prompt or completion)
        priced = has_split and bool(pricing_known)
        cost = (
            prompt * max(0.0, float(input_price or 0.0))
            + completion * max(0.0, float(output_price or 0.0))
        ) / 1_000_000 if priced else 0.0
        with self._lock:
            if not self._enabled:
                return
            now = time.monotonic()
            if self._first_usage_at is None:
                self._first_usage_at = now
            item = self._providers.setdefault(str(provider), {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "unpriced_requests": 0,
            })
            item["requests"] += 1
            item["prompt_tokens"] += prompt
            item["completion_tokens"] += completion
            item["total_tokens"] += total
            item["cost_usd"] += cost
            if not priced:
                item["unpriced_requests"] += 1
            daily_values = {
                "requests": 1,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
                "cost_usd": cost,
                "unpriced_requests": 0 if priced else 1,
            }
        if self._daily_ledger is not None:
            self._daily_ledger.record(daily_values)

    def snapshot(self):
        with self._lock:
            now = time.monotonic()
            elapsed = self._active_elapsed
            if self._active_started_at is not None:
                elapsed += max(0.0, now - self._active_started_at)
            providers = {name: dict(values) for name, values in self._providers.items()}
            enabled = self._enabled
        totals = {
            key: sum(item[key] for item in providers.values())
            for key in (
                "requests", "prompt_tokens", "completion_tokens",
                "total_tokens", "cost_usd", "unpriced_requests",
            )
        }
        totals["elapsed_seconds"] = elapsed
        projected_cost = max(
            0.0, totals["cost_usd"] - self._projection_cost_baseline
        )
        totals["hourly_cost_usd"] = (
            projected_cost * 3600 / elapsed if elapsed >= 10 else None
        )
        totals["providers"] = providers
        totals["enabled"] = enabled
        totals["today"] = (
            self._daily_ledger.snapshot() if self._daily_ledger is not None
            else self._empty_daily_totals()
        )
        return totals

    @staticmethod
    def _empty_daily_totals():
        return {key: 0.0 if key == "cost_usd" else 0 for key in _USAGE_KEYS}


session_usage_meter = TranslationUsageMeter(DailyUsageLedger(os.path.join(
    os.path.dirname(__file__), "logs", "daily_api_usage.json"
)))


class MeteredTranslator:
    """Add accounting to one Translator without changing translation behavior."""

    def __init__(self, translator, provider, input_price=0.0, output_price=0.0):
        self.translator = translator
        self.provider = provider
        self.input_price = input_price
        self.output_price = output_price
        self.pricing_known = bool(input_price or output_price)

    def __getattr__(self, name):
        return getattr(self.translator, name)

    def translate(self, *args, **kwargs):
        upstream = kwargs.get("usage_callback")

        def record(usage):
            session_usage_meter.record(
                self.provider, usage, self.input_price, self.output_price,
                self.pricing_known,
            )
            if upstream:
                upstream(usage)

        kwargs["usage_callback"] = record
        return self.translator.translate(*args, **kwargs)
