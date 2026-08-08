from openai import OpenAI, OpenAIError
import httpx
import os
import re

class Translator:
    def __init__(self, api_key=None, base_url=None, model="MBZUAI-IFM/K2-Think-nothink",
                 target_lang="Chinese", domain_prompt=None):
        """
        Translates text using an LLM.
        
        Args:
            api_key: OpenAI API Key (or set OPENAI_API_KEY env var).
            base_url: Optional base URL (e.g. for local generic server like Ollama/LMStudio).
            model: Model name to use.
            target_lang: The target language for translation.
        """
        self.target_lang = target_lang
        self.model = model
        self.domain_prompt = domain_prompt or (
            "Postgraduate computer science coursework. Preserve computer science "
            "and mathematics terminology accurately, consistently, and in standard academic language."
        )
        
        # If no key provided, check env. If still none, we might be in local mode (no auth) or fail.
        # Some local servers don't need a valid key, but the client requires a string.
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY", "dummy-key-for-local")
            
        if not base_url:
            base_url = os.getenv("OPENAI_BASE_URL")

        self.base_url = base_url
        
        # Create HTTP client with SSL verification disabled (for self-signed certs)
        http_client = httpx.Client(verify=False)
        self.client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
        
        # Logging
        print(f"[Translator] Initialized:")
        print(f"  - Base URL: {base_url or 'https://api.openai.com/v1 (default)'}")
        print(f"  - Model: {model}")
        print(f"  - Target Language: {target_lang}")
        print(f"  - API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else '***'}")
        
        # Context carryover for sentence continuity
        self.previous_text = ""
        self.previous_translation = ""

    def _strip_thinking(self, text):
        """Remove <think>...</think> tags from response (for reasoning models)"""
        # Remove think tags and their content
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return cleaned.strip()

    def translate(self, text, use_context=True, on_update=None, remember_context=True,
                  draft_translation=None):
        """
        Translates the given text. Returns the translated string.
        Uses previous transcription as context for better continuity.
        """
        if not text or not text.strip():
            return ""

        is_qwen_mt = self.model.startswith("qwen-mt-")

        # Qwen-MT is a purpose-built, single-turn translation API. It rejects
        # system messages and receives language selection through extra_body.
        if is_qwen_mt:
            messages = [{"role": "user", "content": text}]
        elif draft_translation:
            system_prompt = (
                f"You are a professional real-time translator and editor. "
                f"Domain context: {self.domain_prompt} "
                f"Improve the draft translation into {self.target_lang}. "
                f"Correct mistranslations using the original text, preserve meaning and terminology, "
                f"and output ONLY the improved translation."
            )
            user_message = (
                f"Original:\n{text}\n\n"
                f"Draft translation:\n{draft_translation}"
            )
        elif use_context and self.previous_text:
            system_prompt = (
                f"You are a professional real-time translator. "
                f"Domain context: {self.domain_prompt} "
                f"Translate the following user input into {self.target_lang}.\\n\\n"
                f"<context>\\n"
                f"Previous Sentence: \"{self.previous_text}\"\\n"
                f"Previous Translation: \"{self.previous_translation}\"\\n"
                f"</context>\\n\\n"
                f"Instructions:\\n"
                f"1. Use the <context> ONLY for continuity (consistency in terminology).\\n"
                f"2. Translate ONLY the text available in the user message.\\n"
                f"3. Do NOT repeat or include the Previous Sentence/Translation in your output.\\n"
                f"4. Output ONLY the translation of the user message."
            )
            user_message = text
        else:
            system_prompt = (
                f"You are a professional real-time translator. "
                f"Domain context: {self.domain_prompt} "
                f"Translate the following user input into {self.target_lang}. "
                f"Do not add any explanations, just output the translation."
            )
            user_message = text

        if not is_qwen_mt:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

        try:
            request_options = {}
            if is_qwen_mt:
                request_options["extra_body"] = {
                    "translation_options": {
                        "source_lang": "auto",
                        "target_lang": self.target_lang,
                        "domains": self.domain_prompt,
                    }
                }
            elif (self.base_url and "siliconflow" in self.base_url and
                  self.model == "deepseek-ai/DeepSeek-V4-Flash"):
                request_options["extra_body"] = {"enable_thinking": False}
            elif self.base_url and "api.deepseek.com" in self.base_url and self.model.startswith("deepseek-v4"):
                request_options["extra_body"] = {"thinking": {"type": "disabled"}}

            completion_options = dict(
                model=self.model,
                messages=messages,
                max_tokens=256,
                timeout=10.0,    # 10s timeout to prevent hanging
                stream=on_update is not None,
                **request_options,
            )
            if not is_qwen_mt:
                completion_options["temperature"] = 0
            response = self.client.chat.completions.create(**completion_options)

            if on_update is not None:
                parts = []
                for chunk in response:
                    if not chunk.choices:
                        continue
                    content = chunk.choices[0].delta.content
                    if content:
                        parts.append(content)
                        partial = self._strip_thinking("".join(parts))
                        if partial:
                            on_update(partial)
                raw_result = "".join(parts).strip()
            else:
                raw_result = response.choices[0].message.content.strip()
            # Strip thinking tags if present
            result = self._strip_thinking(raw_result)
            
            # Store for next translation context
            if remember_context:
                self.previous_text = text
                self.previous_translation = result
            
            return result
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
