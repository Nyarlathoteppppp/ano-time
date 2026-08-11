"""In-memory API token and cost accounting outside the subtitle hot path."""

import threading
import time


class TranslationUsageMeter:
    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = True
        self._started_at = time.monotonic()
        self._first_usage_at = None
        self._active_started_at = None
        self._active_elapsed = 0.0
        self._projection_started = False
        self._projection_cost_baseline = 0.0
        self._providers = {}

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
        return totals


session_usage_meter = TranslationUsageMeter()


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
