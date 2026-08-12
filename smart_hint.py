"""Independent, low-frequency lecture-context inference.

Smart Hint is intentionally outside the subtitle pipeline.  It receives only
finalized English, runs at most once per interval on its own single worker, and
publishes a compact context snapshot for later remote requests.  A failure can
never block, cool down, or reroute live translation.
"""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import threading
import time

import httpx
from openai import OpenAI
from translation_usage import session_usage_meter


DEFAULT_SILICONFLOW_URL = "https://api.siliconflow.cn/v1"
DEFAULT_SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V4-Flash"


@dataclass(frozen=True)
class SmartHint:
    topic: str = ""
    keywords: tuple[str, ...] = ()

    def prompt_text(self):
        items = []
        if self.topic:
            items.append(f"Inferred lecture topic: {self.topic}.")
        if self.keywords:
            items.append("Relevant terms: " + ", ".join(self.keywords) + ".")
        return " ".join(items)


class SmartHintClient:
    """Small OpenAI-compatible client dedicated to summarization only."""

    def __init__(self, *, api_key, base_url, model, timeout_seconds=8.0):
        self.base_url = str(base_url or "").rstrip("/")
        self.model = str(model or "")
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        direct = "siliconflow" in self.base_url
        self._http = httpx.Client(verify=True, trust_env=not direct)
        self._client = OpenAI(
            api_key=str(api_key or ""),
            base_url=self.base_url,
            http_client=self._http,
            max_retries=0,
        )

    def summarize(self, source_segments):
        source = "\n".join(str(item).strip() for item in source_segments if item).strip()
        if not source:
            return SmartHint()
        messages = [
            {
                "role": "system",
                "content": (
                    "You infer short lecture context from finalized English ASR excerpts. "
                    "The subject may be computer science, AI, mathematics, statistics, "
                    "or a related technical course. Correct only obvious ASR errors; do "
                    "not invent facts. Return JSON only: "
                    '{"topic":"up to 12 words","keywords":["up to 10 technical terms"]}.'
                ),
            },
            {"role": "user", "content": "FINALIZED ASR:\n" + source},
        ]
        options = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 180,
            "timeout": self.timeout_seconds,
        }
        if "siliconflow" in self.base_url and self.model == DEFAULT_SILICONFLOW_MODEL:
            options["extra_body"] = {"enable_thinking": False}
        response = self._client.chat.completions.create(**options)
        self._record_usage(getattr(response, "usage", None))
        content = str(response.choices[0].message.content or "").strip()
        return self._parse(content)

    def _record_usage(self, usage):
        """Account for this optional request without coupling it to subtitles."""
        if usage is None:
            return
        def field(name):
            return usage.get(name) if isinstance(usage, dict) else getattr(usage, name, 0)
        try:
            prompt = int(field("prompt_tokens") or 0)
            completion = int(field("completion_tokens") or 0)
            total = int(field("total_tokens") or prompt + completion)
            session_usage_meter.record(
                f"Smart Hint · {self.model}",
                {
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": total,
                    "estimated": False,
                },
                pricing_known=False,
            )
        except (TypeError, ValueError):
            # Usage accounting is strictly best effort.
            return

    @staticmethod
    def _parse(content):
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Smart Hint did not return JSON")
        value = json.loads(content[start:end + 1])
        topic = " ".join(str(value.get("topic", "")).split())[:140]
        raw_keywords = value.get("keywords", [])
        if not isinstance(raw_keywords, list):
            raw_keywords = []
        keywords = []
        for keyword in raw_keywords:
            cleaned = " ".join(str(keyword).split())[:64]
            if cleaned and cleaned not in keywords:
                keywords.append(cleaned)
        return SmartHint(topic=topic, keywords=tuple(keywords[:10]))

    def close(self):
        self._http.close()


class SmartHintScheduler:
    """Keep the latest forty final segments and refresh a hint at low frequency."""

    def __init__(
        self, client, *, interval_seconds=240.0, status_callback=None,
        clock=time.monotonic,
    ):
        self._client = client
        self._interval_seconds = max(30.0, float(interval_seconds))
        self._status_callback = status_callback or (lambda *_args: None)
        self._clock = clock
        self._lock = threading.RLock()
        self._source = deque(maxlen=40)
        self._hint = SmartHint()
        self._source_revision = 0
        self._summarized_revision = 0
        self._next_allowed_at = clock() + self._interval_seconds
        self._future = None
        self._closed = False
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="smart-hint"
        )

    def observe_finalized(self, text):
        """Record finalized source and maybe queue one independent update."""
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return False
        with self._lock:
            if self._closed:
                return False
            self._source.append(cleaned)
            self._source_revision += 1
            now = self._clock()
            if (
                len(self._source) < 4
                or now < self._next_allowed_at
                or (self._future is not None and not self._future.done())
                or self._source_revision == self._summarized_revision
            ):
                return False
            source = tuple(self._source)
            revision = self._source_revision
            self._next_allowed_at = now + self._interval_seconds
            self._status_callback("active", "正在根据最近 40 条原文更新")
            future = self._executor.submit(self._run, source, revision)
            self._future = future
        future.add_done_callback(self._forget)
        return True

    def _run(self, source, revision):
        started = time.perf_counter()
        try:
            hint = self._client.summarize(source)
            with self._lock:
                if self._closed:
                    return
                self._hint = hint
                self._summarized_revision = revision
            detail = hint.topic or "已更新关键词"
            self._status_callback(
                "ok", f"{detail} · {(time.perf_counter() - started):.1f}s"
            )
        except Exception as exc:
            self._status_callback("warning", f"更新失败：{type(exc).__name__}")

    def _forget(self, future):
        with self._lock:
            if self._future is future:
                self._future = None

    def snapshot(self):
        with self._lock:
            return self._hint.prompt_text()

    def source_snapshot(self):
        with self._lock:
            return tuple(self._source)

    def shutdown(self):
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._client.close()


def build_smart_hint_scheduler(settings, status_callback=None):
    if not getattr(settings, "smart_hint_enabled", False):
        return None
    provider = str(getattr(settings, "smart_hint_provider", "siliconflow")).lower()
    api_key = getattr(settings, "smart_hint_api_key", "")
    # SiliconFlow is already a supported provider profile. Reuse its secure
    # Keychain-backed key when the optional Smart Hint field is deliberately
    # left empty; Custom endpoints always require their own explicit key.
    if not api_key and provider == "siliconflow":
        api_key = getattr(settings, "siliconflow_api_key", "")
    if not (
        api_key
        and getattr(settings, "smart_hint_base_url", "")
        and getattr(settings, "smart_hint_model", "")
    ):
        return None
    return SmartHintScheduler(
        SmartHintClient(
            api_key=api_key,
            base_url=settings.smart_hint_base_url,
            model=settings.smart_hint_model,
        ),
        interval_seconds=getattr(settings, "smart_hint_interval_seconds", 240.0),
        status_callback=status_callback,
    )
