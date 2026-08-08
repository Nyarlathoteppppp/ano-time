import json
import os
import threading
import time
from collections import deque
from datetime import date
from math import ceil


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
            item.setdefault("priority", 0)
            item["cooldown_until"] = 0.0
            item["daily_block_date"] = None
            item["recent_attempts"] = deque()
            item["recent_tokens"] = deque()
            self.providers.append(item)
        self.usage_path = usage_path
        self._lock = threading.Lock()
        self._next_index = 0
        self._usage = self._load_usage()

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
        today = date.today().isoformat()
        record = self._usage.get(provider["name"], {})
        if record.get("date") != today:
            record = {"date": today, "attempts": 0}
            self._usage[provider["name"]] = record
            self._save_usage_locked()
        return int(record.get("attempts", 0))

    def _reserve_locked(self, provider, now, estimated_tokens):
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
        if tpm_limit and sum(tokens for _, tokens in token_usage) + estimated_tokens > tpm_limit:
            if token_usage:
                provider["cooldown_until"] = max(
                    provider["cooldown_until"], token_usage[0][0] + 60
                )
            return False
        daily_limit = provider.get("daily_limit")
        daily_attempts = self._daily_attempts_locked(provider)
        if daily_limit and daily_attempts >= daily_limit:
            return False
        attempts.append(now)
        token_usage.append((now, estimated_tokens))
        record = self._usage.setdefault(
            provider["name"], {"date": date.today().isoformat(), "attempts": 0}
        )
        record["attempts"] = daily_attempts + 1
        provider["last_daily_attempts"] = record["attempts"]
        provider["last_minute_requests"] = len(attempts)
        provider["last_minute_tokens"] = sum(tokens for _, tokens in token_usage)
        self._save_usage_locked()
        return True

    def _select_provider(self, excluded, estimated_tokens):
        now = time.monotonic()
        with self._lock:
            count = len(self.providers)
            priorities = sorted({provider["priority"] for provider in self.providers})
            for priority in priorities:
                for offset in range(count):
                    index = (self._next_index + offset) % count
                    provider = self.providers[index]
                    if provider["priority"] != priority:
                        continue
                    if provider["name"] in excluded:
                        continue
                    blocked_date = provider.get("daily_block_date")
                    today = date.today().isoformat()
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
                    if not self._reserve_locked(provider, now, estimated_tokens):
                        continue
                    self._next_index = (index + 1) % count
                    return provider
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
                    provider["daily_block_date"] = date.today().isoformat()
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

    def translate(self, *args, **kwargs):
        excluded = set()
        last_error = None
        estimated_tokens = self._estimate_tokens(args, kwargs)
        while len(excluded) < len(self.providers):
            provider = self._select_provider(excluded, estimated_tokens)
            if provider is None:
                break
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
                    f"estimated_tpm={provider.get('last_minute_tokens', 0)}/{provider['tpm_limit']}"
                )
            quota = f" ({', '.join(quota_parts)})" if quota_parts else ""
            print(f"[Hybrid] Using {provider['name']}{quota}", flush=True)
            try:
                return provider["translator"].translate(*args, **kwargs)
            except TimeoutError:
                # The hard deadline is already exhausted; a failover cannot finish.
                raise
            except Exception as exc:
                last_error = exc
                self._cool_down(provider, exc)
        if last_error:
            raise last_error
        raise RuntimeError("All hybrid translation providers are cooling down or quota-limited")
