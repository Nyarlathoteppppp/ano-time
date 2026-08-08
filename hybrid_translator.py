import json
import os
import threading
import time
from collections import deque
from datetime import date, datetime
from math import ceil
from zoneinfo import ZoneInfo


class HybridTranslator:
    """Round-robin translators with quota-aware, no-retry failover."""

    def __init__(self, providers, usage_path=None):
        if not providers:
            raise ValueError("HybridTranslator requires at least one provider")
        self.providers = []
        for provider in providers:
            item = dict(provider)
            item.setdefault("rpm_limit", None)
            item.setdefault("tpm_limit", None)
            item.setdefault("daily_limit", None)
            item.setdefault("daily_neuron_limit", None)
            item.setdefault("neuron_input_per_million", 0)
            item.setdefault("neuron_output_per_million", 0)
            item.setdefault("daily_timezone", None)
            item.setdefault("priority", 0)
            item["cooldown_until"] = 0.0
            item["daily_block_date"] = None
            item["recent_attempts"] = deque()
            item["recent_tokens"] = deque()
            item["neuron_reservations"] = {}
            self.providers.append(item)
        self.usage_path = usage_path
        self._lock = threading.Lock()
        self._next_index = 0
        self._usage = self._load_usage()
        self._reservation_counter = 0
        self._restore_minute_windows()

    def _today(self, provider):
        timezone = provider.get("daily_timezone")
        if timezone:
            return datetime.now(ZoneInfo(timezone)).date().isoformat()
        return date.today().isoformat()

    def _restore_minute_windows(self):
        wall_now = time.time()
        monotonic_now = time.monotonic()
        for provider in self.providers:
            record = self._usage.get(provider["name"], {})
            for event in record.get("recent", []):
                try:
                    wall_time = float(event["time"])
                    tokens = int(event["tokens"])
                    reservation_id = int(event["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                age = wall_now - wall_time
                if 0 <= age < 60:
                    event_time = monotonic_now - age
                    provider["recent_attempts"].append(event_time)
                    provider["recent_tokens"].append(
                        (event_time, tokens, reservation_id)
                    )
                    self._reservation_counter = max(
                        self._reservation_counter, reservation_id
                    )

    def _load_usage(self):
        if not self.usage_path:
            return {}
        try:
            with open(self.usage_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_usage_locked(self):
        if not self.usage_path:
            return
        try:
            wall_now = time.time()
            monotonic_now = time.monotonic()
            for provider in self.providers:
                record = self._usage.setdefault(
                    provider["name"],
                    {"date": self._today(provider), "attempts": 0},
                )
                record["recent"] = [
                    {
                        "time": wall_now - max(0.0, monotonic_now - event_time),
                        "tokens": tokens,
                        "id": reservation_id,
                    }
                    for event_time, tokens, reservation_id in provider["recent_tokens"]
                    if monotonic_now - event_time < 60
                ]
            directory = os.path.dirname(self.usage_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            temporary = f"{self.usage_path}.tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(self._usage, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, self.usage_path)
        except OSError as exc:
            print(f"[Hybrid] Could not persist provider usage: {exc}", flush=True)

    def _daily_attempts_locked(self, provider):
        today = self._today(provider)
        record = self._usage.get(provider["name"], {})
        if record.get("date") != today:
            record = {"date": today, "attempts": 0, "neurons": 0.0}
            self._usage[provider["name"]] = record
            self._save_usage_locked()
        return int(record.get("attempts", 0))

    def _reserve_locked(self, provider, now, estimated_tokens, estimated_neurons):
        attempts = provider["recent_attempts"]
        while attempts and now - attempts[0] >= 60:
            attempts.popleft()
        token_usage = provider["recent_tokens"]
        while token_usage and now - token_usage[0][0] >= 60:
            token_usage.popleft()
        rpm_limit = provider.get("rpm_limit")
        if rpm_limit and len(attempts) >= rpm_limit:
            provider["cooldown_until"] = max(
                provider["cooldown_until"], attempts[0] + 60
            )
            return False
        tpm_limit = provider.get("tpm_limit")
        if tpm_limit and sum(tokens for _, tokens, _ in token_usage) + estimated_tokens > tpm_limit:
            if token_usage:
                provider["cooldown_until"] = max(
                    provider["cooldown_until"], token_usage[0][0] + 60
                )
            return False
        daily_limit = provider.get("daily_limit")
        daily_attempts = self._daily_attempts_locked(provider)
        if daily_limit and daily_attempts >= daily_limit:
            return False
        record = self._usage.setdefault(
            provider["name"],
            {"date": self._today(provider), "attempts": 0, "neurons": 0.0},
        )
        daily_neuron_limit = provider.get("daily_neuron_limit")
        current_neurons = float(record.get("neurons", 0.0))
        if daily_neuron_limit and current_neurons + estimated_neurons > daily_neuron_limit:
            return False
        attempts.append(now)
        self._reservation_counter += 1
        reservation_id = self._reservation_counter
        token_usage.append((now, estimated_tokens, reservation_id))
        record["attempts"] = daily_attempts + 1
        if daily_neuron_limit:
            record["neurons"] = current_neurons + estimated_neurons
            provider["neuron_reservations"][reservation_id] = estimated_neurons
            provider["last_daily_neurons"] = record["neurons"]
        provider["last_daily_attempts"] = record["attempts"]
        provider["last_minute_requests"] = len(attempts)
        provider["last_minute_tokens"] = sum(tokens for _, tokens, _ in token_usage)
        self._save_usage_locked()
        return reservation_id

    def _record_actual_usage(self, provider, reservation_id, usage):
        if isinstance(usage, dict):
            actual_tokens = int(usage.get("total_tokens") or 0)
            actual_neurons = float(usage.get("neurons") or 0.0)
        else:
            actual_tokens = int(usage or 0)
            actual_neurons = 0.0
        with self._lock:
            updated = deque()
            for event_time, tokens, event_id in provider["recent_tokens"]:
                if event_id == reservation_id:
                    tokens = max(0, int(actual_tokens))
                updated.append((event_time, tokens, event_id))
            provider["recent_tokens"] = updated
            provider["last_minute_tokens"] = sum(
                tokens for _, tokens, _ in updated
            )
            if provider.get("daily_neuron_limit"):
                reserved = provider["neuron_reservations"].pop(reservation_id, 0.0)
                record = self._usage.setdefault(
                    provider["name"],
                    {"date": self._today(provider), "attempts": 0, "neurons": 0.0},
                )
                record["neurons"] = max(
                    0.0, float(record.get("neurons", 0.0)) - reserved + actual_neurons
                )
                provider["last_daily_neurons"] = record["neurons"]
            self._save_usage_locked()

    def _select_provider(
        self,
        excluded,
        estimated_tokens,
        estimated_neurons_by_name,
        allowed_names=None,
    ):
        now = time.monotonic()
        with self._lock:
            count = len(self.providers)
            priorities = sorted({provider["priority"] for provider in self.providers})
            for priority in priorities:
                for offset in range(count):
                    index = (self._next_index + offset) % count
                    provider = self.providers[index]
                    if allowed_names is not None and provider["name"] not in allowed_names:
                        continue
                    if provider["priority"] != priority:
                        continue
                    if provider["name"] in excluded:
                        continue
                    blocked_date = provider.get("daily_block_date")
                    today = self._today(provider)
                    if blocked_date:
                        if blocked_date == today:
                            continue
                        provider["daily_block_date"] = None
                        print(
                            f"[Hybrid] {provider['name']} daily quota reset; returning to free pool",
                            flush=True,
                        )
                    if now < provider["cooldown_until"]:
                        continue
                    if provider["cooldown_until"]:
                        provider["cooldown_until"] = 0.0
                        print(
                            f"[Hybrid] {provider['name']} minute quota reset; returning to free pool",
                            flush=True,
                        )
                    reservation_id = self._reserve_locked(
                        provider,
                        now,
                        estimated_tokens,
                        estimated_neurons_by_name.get(provider["name"], 0.0),
                    )
                    if not reservation_id:
                        continue
                    self._next_index = (index + 1) % count
                    return provider, reservation_id
        return None

    @staticmethod
    def _estimate_tokens(args, kwargs):
        # Conservative budget: English is roughly 4 chars/token; CJK is close
        # to 1 char/token. Include the fixed system prompt and likely output.
        text = str(args[0]) if args else str(kwargs.get("text", ""))
        context = str(kwargs.get("context_text") or "")
        combined = text + context
        cjk = sum("\u3400" <= char <= "\u9fff" for char in combined)
        non_cjk = max(0, len(combined) - cjk)
        input_tokens = cjk + ceil(non_cjk / 4)
        output_reserve = min(160, max(48, ceil(len(text) / 3)))
        return max(1, input_tokens + 220 + output_reserve)

    @staticmethod
    def _estimate_neurons(provider, args, kwargs):
        text = str(args[0]) if args else str(kwargs.get("text", ""))
        context = str(kwargs.get("context_text") or "")
        combined = text + context
        cjk = sum("\u3400" <= char <= "\u9fff" for char in combined)
        input_tokens = cjk + ceil(max(0, len(combined) - cjk) / 4) + 220
        output_tokens = min(160, max(48, ceil(len(text) / 3)))
        return (
            input_tokens * provider.get("neuron_input_per_million", 0)
            + output_tokens * provider.get("neuron_output_per_million", 0)
        ) / 1_000_000

    @staticmethod
    def _status_code(exc):
        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
        return status

    @staticmethod
    def _retry_after(exc):
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", {}) or {}
        try:
            return max(1.0, float(headers.get("retry-after", 0)))
        except (TypeError, ValueError):
            return 0.0

    def _cool_down(self, provider, exc):
        status = self._status_code(exc)
        message = str(exc).casefold()
        if status == 429:
            if any(word in message for word in ("daily", "per day", "rpd")):
                seconds = 0
                with self._lock:
                    provider["daily_block_date"] = self._today(provider)
            else:
                seconds = max(60.0, self._retry_after(exc))
        elif status in (400, 401, 403, 404):
            seconds = 15 * 60
        else:
            seconds = 60
        if seconds:
            with self._lock:
                provider["cooldown_until"] = max(
                    provider["cooldown_until"], time.monotonic() + seconds
                )
        print(
            f"[Hybrid] {provider['name']} unavailable "
            f"(status={status or type(exc).__name__}); "
            f"{'blocked for today' if not seconds else f'cooling down {seconds:.0f}s'}",
            flush=True,
        )

    def _translate(self, args, kwargs, allowed_names=None):
        excluded = set()
        last_error = None
        estimated_tokens = self._estimate_tokens(args, kwargs)
        estimated_neurons_by_name = {
            provider["name"]: self._estimate_neurons(provider, args, kwargs)
            for provider in self.providers
        }
        eligible_count = sum(
            allowed_names is None or provider["name"] in allowed_names
            for provider in self.providers
        )
        while len(excluded) < eligible_count:
            selection = self._select_provider(
                excluded,
                estimated_tokens,
                estimated_neurons_by_name,
                allowed_names=allowed_names,
            )
            if selection is None:
                break
            provider, reservation_id = selection
            excluded.add(provider["name"])
            quota_parts = []
            if provider.get("daily_limit"):
                quota_parts.append(
                    f"daily={provider.get('last_daily_attempts', 0)}/{provider['daily_limit']}"
                )
            if provider.get("rpm_limit"):
                quota_parts.append(
                    f"rpm={provider.get('last_minute_requests', 0)}/{provider['rpm_limit']}"
                )
            if provider.get("tpm_limit"):
                quota_parts.append(
                    f"reserved_tpm={provider.get('last_minute_tokens', 0)}/{provider['tpm_limit']}"
                )
            if provider.get("daily_neuron_limit"):
                quota_parts.append(
                    f"neurons={provider.get('last_daily_neurons', 0):.2f}/"
                    f"{provider['daily_neuron_limit']}"
                )
            quota = f" ({', '.join(quota_parts)})" if quota_parts else ""
            print(f"[Hybrid] Using {provider['name']}{quota}", flush=True)
            attempt_kwargs = dict(kwargs)
            global_deadline = kwargs.get("deadline")
            if (
                global_deadline is not None
                and len(excluded) == 1
                and len(self.providers) > 1
                and global_deadline - time.monotonic() > 2.0
            ):
                # Reserve time for a second provider when the first endpoint hangs.
                attempt_kwargs["deadline"] = min(
                    global_deadline, time.monotonic() + 1.5
                )
            attempt_kwargs["usage_callback"] = lambda total, p=provider, r=reservation_id: (
                self._record_actual_usage(p, r, total)
            )
            try:
                return provider["translator"].translate(*args, **attempt_kwargs)
            except TimeoutError as exc:
                last_error = exc
                self._record_actual_usage(provider, reservation_id, 0)
                self._cool_down(provider, exc)
                deadline = kwargs.get("deadline")
                if deadline is not None and time.monotonic() >= deadline:
                    break
            except Exception as exc:
                last_error = exc
                self._record_actual_usage(provider, reservation_id, 0)
                self._cool_down(provider, exc)
        if last_error:
            raise last_error
        raise RuntimeError("All hybrid translation providers are cooling down or quota-limited")

    def translate(self, *args, **kwargs):
        return self._translate(args, kwargs)

    def translate_only(self, provider_names, *args, **kwargs):
        """Translate using only the named providers while sharing quota state."""
        return self._translate(args, kwargs, allowed_names=set(provider_names))

    def translate_excluding(self, provider_names, *args, **kwargs):
        """Translate without selected providers while sharing quota state."""
        excluded = set(provider_names)
        allowed = {
            provider["name"]
            for provider in self.providers
            if provider["name"] not in excluded
        }
        return self._translate(args, kwargs, allowed_names=allowed)
