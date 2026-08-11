from openai import OpenAI, OpenAIError
import httpx
import os
import re
import time

from glossary import CourseGlossary
from math_subtitles import safe_normalize_math_subtitles

class Translator:
    def __init__(self, api_key=None, base_url=None, model="MBZUAI-IFM/K2-Think-nothink",
                 target_lang="Chinese", domain_prompt=None, deadline_seconds=3.0,
                 glossary_path=None):
        """
        Translates text using an LLM.
        
        Args:
            api_key: OpenAI API Key (or set OPENAI_API_KEY env var).
            base_url: Optional base URL (e.g. for local generic server like Ollama/LMStudio).
            model: Model name to use.
            target_lang: The target language for translation.
        """
        self.target_lang = target_lang
        self.prompt_target_lang = self._prompt_target_language(target_lang)
        self.model = model
        self.deadline_seconds = max(0.1, float(deadline_seconds))
        self.domain_prompt = domain_prompt or (
            "Postgraduate Computer Science–AI coursework. Preserve standard terminology "
            "in AI, machine learning, probability and statistics, linear algebra, "
            "optimization, and software engineering."
        )
        self.asr_correction_prompt = (
            "The source comes from ASR and may contain recognition errors."
        )
        paths = (
            glossary_path
            if isinstance(glossary_path, (list, tuple))
            else (glossary_path,)
        )
        self.glossary = CourseGlossary.from_files(paths)
        
        # If no key provided, check env. If still none, we might be in local mode (no auth) or fail.
        # Some local servers don't need a valid key, but the client requires a string.
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY", "dummy-key-for-local")
            
        if not base_url:
            base_url = os.getenv("OPENAI_BASE_URL")

        self.base_url = base_url
        
        # The local proxy is useful for some providers, but Groq/Gemini are
        # directly reachable and a stale desktop proxy can break their TLS.
        direct_provider = bool(
            base_url and any(
                host in base_url
                for host in (
                    "api.groq.com",
                    "api.cerebras.ai",
                    "generativelanguage.googleapis.com",
                    "api.cloudflare.com",
                )
            )
        )
        http_client = httpx.Client(verify=True, trust_env=not direct_provider)
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            max_retries=0,
        )
        
        # Logging
        print(f"[Translator] Initialized:")
        print(f"  - Base URL: {base_url or 'https://api.openai.com/v1 (default)'}")
        print(f"  - Model: {model}")
        print(f"  - Target Language: {target_lang}")
        print(f"  - API Key: {'configured' if api_key else 'missing'}")
        
        # Context carryover for sentence continuity
        self.previous_text = ""
        self.previous_translation = ""

    @staticmethod
    def _prompt_target_language(target_lang):
        """Remove Simplified/Traditional ambiguity for generic LLM prompts."""
        normalized = str(target_lang or "").strip().lower().replace("_", "-")
        if normalized in {
            "chinese", "simplified chinese", "zh", "zh-cn", "zh-hans"
        }:
            return "Simplified Chinese"
        return target_lang

    def _strip_thinking(self, text):
        """Remove <think>...</think> tags from response (for reasoning models)"""
        # Remove think tags and their content
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return cleaned.strip()

    def warmup(self, timeout=2.5):
        """Prime one remote connection/model without touching subtitle state."""
        if not (
            self.base_url
            and "generativelanguage.googleapis.com" in self.base_url
            and self.model.startswith("gemini-")
        ):
            return False
        response = None
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": "Translate to Chinese: ready"}
                ],
                max_tokens=4,
                timeout=max(0.1, float(timeout)),
                stream=True,
                reasoning_effort="minimal",
            )
            for chunk in response:
                if not chunk.choices:
                    continue
                if chunk.choices[0].delta.content:
                    return True
            return True
        finally:
            close = getattr(response, "close", None)
            if close:
                close()

    @staticmethod
    def _report_usage(usage, callback):
        if not usage or not callback:
            return False
        def value(name):
            return usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)

        total = value("total_tokens")
        if total is None:
            return False
        try:
            callback({
                "total_tokens": int(total),
                "prompt_tokens": int(value("prompt_tokens") or 0),
                "completion_tokens": int(value("completion_tokens") or 0),
                "neurons": float(value("neurons") or 0.0),
                "estimated": False,
            })
        except Exception as exc:
            print(f"[Translator] Usage callback failed: {exc}", flush=True)
        return True

    @staticmethod
    def _estimate_token_count(text):
        """Cheap provider-neutral fallback; never presented as exact usage."""
        text = str(text or "")
        if not text:
            return 0
        ascii_count = sum(1 for character in text if ord(character) < 128)
        non_ascii_count = len(text) - ascii_count
        return max(1, (ascii_count + 3) // 4 + non_ascii_count)

    @classmethod
    def _estimated_usage(cls, messages, completion):
        prompt = 2 + sum(
            4 + cls._estimate_token_count(message.get("content", ""))
            for message in messages
        )
        output = cls._estimate_token_count(completion)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": output,
            "total_tokens": prompt + output,
            "estimated": True,
        }

    def translate(self, text, use_context=True, on_update=None, remember_context=True,
                  draft_translation=None, previous_preview=None,
                  context_text=None, deadline=None,
                  usage_callback=None, failure_scope="final",
                  prefer_preview_continuity=False):
        """
        Translates the given text. Returns the translated string.
        Uses previous transcription as context for better continuity.
        """
        if not text or not text.strip():
            return ""

        if deadline is None:
            deadline = time.monotonic() + self.deadline_seconds
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("AI translation deadline expired before request start")

        is_qwen_mt = self.model.startswith("qwen-mt-")
        matched_terms = self.glossary.match(text)
        terminology_prompt = ""
        if matched_terms:
            pairs = "; ".join(
                f"{term.source} = {term.target}" for term in matched_terms
            )
            terminology_prompt = f" Required terminology: {pairs}."

        output_constraint = (
            f"Return only the complete {self.prompt_target_lang} translation "
            "of CURRENT. Write every clearly stated mathematical variable, operator, "
            "and formula as inline LaTeX; never transliterate symbol names. Otherwise "
            "use plain text. No Markdown or explanations."
        )

        # Qwen-MT is a purpose-built, single-turn translation API. It rejects
        # system messages and receives language selection through extra_body.
        if is_qwen_mt:
            messages = [{"role": "user", "content": text}]
        elif draft_translation:
            system_prompt = (
                f"Domain: {self.domain_prompt} {self.asr_correction_prompt} "
                "Correct DRAFT using CURRENT; preserve meaning and terminology. "
                f"{output_constraint}{terminology_prompt}"
            )
            user_message = (
                f"DRAFT:\n{draft_translation}\n\nCURRENT:\n{text}"
            )
        elif previous_preview:
            continuity_rule = (
                "Correctness is mandatory. If wording in PREVIOUS remains "
                "semantically accurate for CURRENT, preserve its exact wording "
                "and word order; change only the text required to correct or "
                "complete CURRENT."
                if prefer_preview_continuity else
                "Correctness overrides continuity. Preserve wording from PREVIOUS "
                "only where it remains accurate for CURRENT."
            )
            system_prompt = (
                f"Domain: {self.domain_prompt} "
                f"{self.asr_correction_prompt} "
                f"{continuity_rule} Use CONTEXT only for "
                f"references and terminology. {output_constraint}{terminology_prompt}"
            )
            context_block = (
                f"\n\nCONTEXT:\n{context_text}" if context_text else ""
            )
            user_message = (
                f"PREVIOUS:\n{previous_preview}"
                f"{context_block}\n\nCURRENT:\n{text}"
            )
        elif context_text:
            system_prompt = (
                f"Domain: {self.domain_prompt} "
                f"{self.asr_correction_prompt} "
                "Use CONTEXT only for references and terminology. "
                f"{output_constraint}{terminology_prompt}"
            )
            user_message = f"CONTEXT:\n{context_text}\n\nCURRENT:\n{text}"
        elif use_context and self.previous_text:
            system_prompt = (
                f"Domain: {self.domain_prompt} {self.asr_correction_prompt} "
                "Use PREVIOUS only for terminology continuity. "
                f"{output_constraint}{terminology_prompt}"
            )
            user_message = (
                f"PREVIOUS:\n{self.previous_text}\n\nCURRENT:\n{text}"
            )
        else:
            system_prompt = (
                f"Domain: {self.domain_prompt} {self.asr_correction_prompt} "
                f"{output_constraint}{terminology_prompt}"
            )
            user_message = f"CURRENT:\n{text}"

        if not is_qwen_mt:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

        try:
            request_options = {}
            if is_qwen_mt:
                translation_options = {
                    "source_lang": "auto",
                    "target_lang": self.target_lang,
                    "domains": f"{self.domain_prompt} {self.asr_correction_prompt}",
                }
                if matched_terms:
                    translation_options["terms"] = [
                        {"source": term.source, "target": term.target}
                        for term in matched_terms
                    ]
                request_options["extra_body"] = {
                    "translation_options": translation_options
                }
            elif (self.base_url and "siliconflow" in self.base_url and
                  self.model == "deepseek-ai/DeepSeek-V4-Flash"):
                request_options["extra_body"] = {"enable_thinking": False}
            elif self.base_url and "api.deepseek.com" in self.base_url and self.model.startswith("deepseek-v4"):
                request_options["extra_body"] = {"thinking": {"type": "disabled"}}

            if self.base_url and "api.groq.com" in self.base_url and self.model.startswith("openai/gpt-oss-"):
                request_options["reasoning_effort"] = "low"
            if self.base_url and "api.cerebras.ai" in self.base_url and self.model == "gpt-oss-120b":
                request_options["reasoning_effort"] = "low"
            if self.base_url and "api.cloudflare.com" in self.base_url and self.model == "@cf/zai-org/glm-4.7-flash":
                request_options["extra_body"] = {
                    "chat_template_kwargs": {"enable_thinking": False}
                }

            completion_options = dict(
                model=self.model,
                messages=messages,
                max_tokens=256,
                timeout=max(0.1, remaining),
                stream=on_update is not None,
                **request_options,
            )
            metered_stream = bool(
                on_update is not None and self.base_url and any(
                    host in self.base_url
                    for host in (
                        "api.groq.com",
                        "generativelanguage.googleapis.com",
                        "api.cloudflare.com",
                    )
                )
            )
            if metered_stream:
                completion_options["stream_options"] = {"include_usage": True}
            is_gemini_35 = (
                self.base_url and "generativelanguage.googleapis.com" in self.base_url
                and self.model.startswith("gemini-3.5-")
            )
            if is_gemini_35:
                # Translation does not need multi-step reasoning. Pin the
                # lowest supported effort so a future provider default cannot
                # silently add thinking latency or billable thinking tokens.
                completion_options["reasoning_effort"] = "minimal"
            if not is_qwen_mt and not is_gemini_35:
                completion_options["temperature"] = 0
            response = self.client.chat.completions.create(**completion_options)

            if time.monotonic() >= deadline:
                close = getattr(response, "close", None)
                if close:
                    close()
                raise TimeoutError("AI translation exceeded its hard deadline")

            if on_update is not None:
                parts = []
                stream_usage = None
                last_display_partial = ""
                try:
                    for chunk in response:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("AI translation exceeded its hard deadline")
                        usage = getattr(chunk, "usage", None)
                        if usage:
                            stream_usage = usage
                        if not chunk.choices:
                            continue
                        content = chunk.choices[0].delta.content
                        if content:
                            parts.append(content)
                            partial = self._strip_thinking("".join(parts))
                            if partial:
                                display_partial = safe_normalize_math_subtitles(
                                    partial, final=False
                                )
                                if (
                                    display_partial
                                    and display_partial != last_display_partial
                                ):
                                    on_update(display_partial)
                                    last_display_partial = display_partial
                finally:
                    close = getattr(response, "close", None)
                    if close:
                        close()
                raw_result = "".join(parts).strip()
                usage_reported = self._report_usage(
                    stream_usage, usage_callback
                )
            else:
                raw_result = response.choices[0].message.content.strip()
                usage_reported = self._report_usage(
                    getattr(response, "usage", None), usage_callback
                )

            if usage_callback and not usage_reported:
                try:
                    usage_callback(self._estimated_usage(messages, raw_result))
                except Exception as exc:
                    # Optional accounting must never turn a successful
                    # translation into a subtitle failure.
                    print(
                        f"[Translator] Usage callback failed: {exc}",
                        flush=True,
                    )

            if time.monotonic() >= deadline:
                raise TimeoutError("AI translation exceeded its hard deadline")
            # Strip thinking tags if present
            result = safe_normalize_math_subtitles(
                self._strip_thinking(raw_result), final=True
            )
            
            # Store for next translation context
            if remember_context:
                self.previous_text = text
                self.previous_translation = result
            
            return result
        except TimeoutError as e:
            print(f"Translation Timeout: {e}")
            raise
        except OpenAIError as e:
            print(f"Translation Error: {e}")
            raise
        except Exception as e:
            print(f"Unexpected Error: {e}")
            raise

if __name__ == "__main__":
    # Test
    print("Testing Translator (simulated)...")
    # This will likely fail if no real server is running, so we wrap in try
    t = Translator(target_lang="Spanish")
    print(t.translate("Hello world"))
