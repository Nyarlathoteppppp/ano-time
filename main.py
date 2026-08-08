import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import sys
import signal
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from audio_capture import AudioCapture
from system_audio_capture import SystemAudioCapture
from transcriber import Transcriber
from translator import Translator
from hybrid_translator import HybridTranslator
from overlay_window import OverlayWindow
from config import config
from runtime_log import log_stage
from stable_prefix import StablePrefixTracker
from groq_bridge import GroqBridgeGate

class WorkerSignals(QObject):
    # (chunk_id, original, translated, ASR state: "partial" | "final")
    update_text = pyqtSignal(int, str, str, str)
    pipeline_error = pyqtSignal(str)

class Pipeline(QObject):
    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()
        self.running = True
        self._translation_state_lock = threading.Lock()
        self._partial_versions = {}
        self._last_partial_text = {}
        self._finalized_chunks = set()
        self._translation_ranks = {}
        self._context_lock = threading.Lock()
        self._last_finalized_segment = ""
        self._refine_queue_lock = threading.RLock()
        self._refine_futures = {}
        self._groq_bridge_gate = GroqBridgeGate(
            max_per_minute=15,
            duplicate_window=30.0,
        )
        
        # Print config for debugging
        config.print_config()
        
        # Initialize components
        audio_capture_class = (
            SystemAudioCapture if config.device_index == "system" else AudioCapture
        )
        self.audio = audio_capture_class(
            device_index=config.device_index,
            sample_rate=config.sample_rate,
            silence_threshold=config.silence_threshold,
            silence_duration=config.silence_duration,
            chunk_duration=config.chunk_duration,
            max_phrase_duration=config.max_phrase_duration,
            streaming_mode=config.streaming_mode,
            streaming_interval=config.streaming_interval,
            streaming_step_size=config.streaming_step_size,
            streaming_overlap=config.streaming_overlap
        )
        log_stage(
            "audio_backend",
            detail=(
                f"class={audio_capture_class.__name__} "
                f"configured_device={config.device_index}"
            ),
        )
        
        # Initialize Transcriber
        print(f"[Pipeline] Initializing Transcriber with backend={config.asr_backend}, device={config.whisper_device}...")
        
        # Determine model size based on backend
        if config.asr_backend == "funasr":
            model_size = config.funasr_model
        else:
            model_size = config.whisper_model
            
        self.transcriber = None
        self.apple_transcriber = None
        if config.asr_backend != "apple":
            self.transcriber = Transcriber(
                backend=config.asr_backend,
                model_size=model_size,
                device=config.whisper_device,
                compute_type=config.whisper_compute_type,
                language=config.source_language
            )
        
        # Initialize Translator
        print(f"[Pipeline] Initializing Translator (target={config.target_lang})...")
        translator_options = dict(
            target_lang=config.target_lang,
            domain_prompt=config.translation_domain,
            deadline_seconds=config.ai_deadline_seconds,
            glossary_path=config.glossary_path,
        )
        if config.translation_provider == "Fast Free Pool → Qwen-MT":
            providers = []
            if config.groq_api_key:
                providers.append({
                    "name": "Groq GPT-OSS 20B",
                    "translator": Translator(
                        base_url="https://api.groq.com/openai/v1",
                        api_key=config.groq_api_key,
                        model="openai/gpt-oss-20b",
                        **translator_options,
                    ),
                    "rpm_limit": 30,
                    "tpm_limit": 8000,
                    "daily_limit": 1000,
                    "daily_timezone": "UTC",
                    "priority": 3,
                })
            if config.cloudflare_account_id and config.cloudflare_api_token:
                providers.append({
                    "name": "Cloudflare GLM-4.7-Flash",
                    "translator": Translator(
                        base_url=(
                            "https://api.cloudflare.com/client/v4/accounts/"
                            f"{config.cloudflare_account_id}/ai/v1"
                        ),
                        api_key=config.cloudflare_api_token,
                        model="@cf/zai-org/glm-4.7-flash",
                        **translator_options,
                    ),
                    "daily_neuron_limit": 10000,
                    "neuron_input_per_million": 5500,
                    "neuron_output_per_million": 36400,
                    "daily_timezone": "UTC",
                    "priority": 1,
                })
            if config.gemini_api_key:
                providers.append({
                    "name": "Gemini 3.5 Flash-Lite",
                    "translator": Translator(
                        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                        api_key=config.gemini_api_key,
                        model="gemini-3.5-flash-lite",
                        **translator_options,
                    ),
                    "rpm_limit": 15,
                    "tpm_limit": 250000,
                    "daily_limit": 500,
                    "daily_timezone": "America/Los_Angeles",
                    "priority": 0,
                })
            if config.qwen_mt_api_key and config.qwen_mt_base_url:
                providers.append({
                    "name": "Qwen-MT Flash fallback",
                    "translator": Translator(
                        base_url=config.qwen_mt_base_url,
                        api_key=config.qwen_mt_api_key,
                        model="qwen-mt-flash",
                        **translator_options,
                    ),
                    "priority": 3,
                })
            self.translator = HybridTranslator(
                providers,
                usage_path=os.path.join(os.path.dirname(__file__), "logs", "provider_usage.json"),
            )
        else:
            self.translator = Translator(
                base_url=config.api_base_url,
                api_key=config.api_key,
                model=config.model,
                **translator_options,
            )

        self.fast_translator = None
        if config.fast_translation_backend == "apple":
            try:
                from apple_translation import AppleTranslator
                self.fast_translator = AppleTranslator(
                    source=config.source_language or "en",
                    target=config.target_lang,
                )
            except Exception as exc:
                print(f"[Pipeline] Apple Translation unavailable, using LLM only: {exc}")
        
        # Warmup Transcriber (Critical for MLX/GPU)
        if self.transcriber:
            self.transcriber.warmup()

    def _emit_ranked_translation(self, chunk_id, text, translated, state, rank):
        """Prevent a late draft from replacing a newer translation stage."""
        with self._translation_state_lock:
            current_rank = self._translation_ranks.get(chunk_id, 0)
            if rank < current_rank:
                return False
            self._translation_ranks[chunk_id] = rank
        self.signals.update_text.emit(chunk_id, text, translated, state)
        return True

    def start(self):
        """Start the processing pipeline in a dedicated thread"""
        # self.audio.start() # DISABLE: Generator manages its own stream. calling this causes double-stream error on macOS
        self.thread = threading.Thread(target=self.processing_loop)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        print("\n[Pipeline] Stopping...")
        self.running = False
        self.audio.stop()
        if hasattr(self, "thread") and self.thread.is_alive():
            self.thread.join(timeout=2)
        if self.fast_translator:
            self.fast_translator.stop()
        print("[Pipeline] Stopped.")

    def processing_loop(self):
        """Fully parallel pipeline: multiple concurrent transcription + translation"""
        if config.asr_backend == "apple":
            self._processing_loop_apple()
            return

        print("Pipeline processing loop started (FULLY PARALLEL mode).")
        
        # Create multiple transcribers for concurrent processing
        # CHECK: If using MLX, force 1 worker (MLX is not thread-safe for parallel inference in this way)
        is_mlx = (config.asr_backend == "mlx")
        
        if is_mlx:
            print("[Pipeline] MLX backend detected - forcing single worker (MLX uses GPU parallelism internaly)")
            num_transcription_workers = 1
        else:
            num_transcription_workers = config.transcription_workers
            
        print(f"[Pipeline] Using {num_transcription_workers} transcription workers...")
        
        # Determine model size based on backend
        if config.asr_backend == "funasr":
            model_size = config.funasr_model
        else:
            model_size = config.whisper_model
        
        transcribers = [self.transcriber]  # Reuse existing one
        for i in range(num_transcription_workers - 1):
            t = Transcriber(
                backend=config.asr_backend,
                model_size=model_size,
                device=config.whisper_device,
                compute_type=config.whisper_compute_type,
                language=config.source_language
            )
            transcribers.append(t)
        """Accumulating Buffer Processing Loop (Word-by-Word Streaming)"""
        print("[Pipeline] processing loop started (Accumulating Mode).")
        
        import numpy as np
        
        # Executors
        transcribe_executor = ThreadPoolExecutor(max_workers=1) # Serial transcription
        translate_executor = ThreadPoolExecutor(max_workers=2)
        
        # State
        buffer = np.array([], dtype=np.float32)
        chunk_id = 1
        last_update_time = time.time()
        phrase_start_time = time.time()
        
        # Generator yielding small chunks (e.g. 0.2s)
        audio_gen = self.audio.generator()
        
        # Context Management
        self.last_final_text = ""

        try:
            for audio_chunk in audio_gen:
                if not self.running:
                    break
                buffer = np.concatenate([buffer, audio_chunk])
                now = time.time()
                buffer_duration = len(buffer) / self.audio.sample_rate
                
                # Check silence for finalization
                # Use configured silence duration/threshold
                is_silence = False
                min_silence_dur = config.silence_duration # e.g. 1.0s
                
                # Only check silence if we have enough buffer
                if buffer_duration > min_silence_dur:
                     # Check tail of silence duration
                    tail = buffer[-int(self.audio.sample_rate * min_silence_dur):]
                    rms = np.sqrt(np.mean(tail**2))
                    if rms < self.audio.silence_threshold:
                        is_silence = True
                        
                # Dynamic VAD Logic
                # 1. Standard: > 2.0s duration AND > 1.0s silence (Configured)
                standard_cut = (is_silence and buffer_duration > 1.0)
                
                # 2. Soft Limit: > 6.0s duration AND > 0.4s silence (Catch brief pauses to avoid huge latency)
                soft_limit_cut = False
                if buffer_duration > 6.0:
                    # Check shorter silence tail (0.4s)
                    short_tail_samps = int(self.audio.sample_rate * 0.4)
                    if len(buffer) > short_tail_samps:
                        t_rms = np.sqrt(np.mean(buffer[-short_tail_samps:]**2))
                        if t_rms < self.audio.silence_threshold:
                            soft_limit_cut = True
                            
                # 3. Hard Limit: > max_phrase_duration (Force cut)
                hard_limit_cut = (buffer_duration > self.audio.max_phrase_duration)

                should_finalize = standard_cut or soft_limit_cut or hard_limit_cut
                
                if should_finalize and buffer_duration > 0.5:
                    # FINALIZE
                    final_buffer = buffer.copy()
                    cid = chunk_id
                    with self._translation_state_lock:
                        self._finalized_chunks.add(cid)
                        self._partial_versions[cid] = self._partial_versions.get(cid, 0) + 1
                    
                    # Store current prompt to pass to task (thread safety)
                    prompt = self.last_final_text
                    
                    # PRE-CHECK: Is the entire buffer actually silence?
                    # (Prevent infinite loop of repeating prompt on empty audio)
                    overall_rms = np.sqrt(np.mean(final_buffer**2))
                    if overall_rms < self.audio.silence_threshold:
                         print(f"[Pipeline] Skipped silent chunk {cid} (RMS={overall_rms:.4f})")
                    else:
                        # Submit Final Task
                        # Pass prompt AND translate_executor for async translation
                        transcribe_executor.submit(self._process_final_chunk, final_buffer, cid, prompt, translate_executor)
                    
                    # Reset
                    buffer = np.array([], dtype=np.float32)
                    chunk_id += 1
                    phrase_start_time = now
                    last_update_time = now
                    
                # 2. Partial Update if: Interval passed AND not finalizing
                elif now - last_update_time > config.update_interval and buffer_duration > 0.5:
                    # PARTIAL UPDATE
                    partial_buffer = buffer.copy()
                    prompt = self.last_final_text
                    
                    # RMS Check to avoid partial hallucination on silence
                    rms = np.sqrt(np.mean(partial_buffer**2))
                    if rms > self.audio.silence_threshold:
                        transcribe_executor.submit(
                            self._process_partial_chunk,
                            partial_buffer,
                            chunk_id,
                            prompt,
                            translate_executor
                        )
                    
                    last_update_time = now
                    
        except Exception as e:
            print(f"[Pipeline] Error in loop: {e}")
            log_stage("pipeline", status="error", detail=str(e))
            self.signals.pipeline_error.emit(str(e))
        finally:
            transcribe_executor.shutdown(wait=False)
            translate_executor.shutdown(wait=False)

    def _processing_loop_apple(self):
        """Feed PCM audio to Apple's native streaming speech recognizer."""
        from apple_transcriber import AppleSpeechTranscriber

        fast_executor = ThreadPoolExecutor(max_workers=1)
        refine_executor = ThreadPoolExecutor(max_workers=2)
        state_lock = threading.Lock()
        state = {
            "chunk_id": 1,
            "audio_started_at": None,
            "first_partial_at": None,
            "stable_tracker": StablePrefixTracker(
                agreement_window=config.stable_prefix_window,
                min_growth_words=config.stable_prefix_min_words,
            ),
        }

        def on_result(text, is_final):
            if not self.running:
                return
            text = " ".join(text.split())
            if not text:
                return
            now = time.monotonic()
            with state_lock:
                chunk_id = state["chunk_id"]
                segment_started_at = state["audio_started_at"] or now
                first_partial_at = state["first_partial_at"]

                if is_final:
                    with self._translation_state_lock:
                        self._finalized_chunks.add(chunk_id)
                        self._partial_versions[chunk_id] = self._partial_versions.get(chunk_id, 0) + 1
                    state["chunk_id"] += 1
                    state["audio_started_at"] = None
                    state["first_partial_at"] = None
                    state["stable_tracker"] = StablePrefixTracker(
                        agreement_window=config.stable_prefix_window,
                        min_growth_words=config.stable_prefix_min_words,
                    )
                else:
                    if first_partial_at is None:
                        first_partial_at = now
                        state["first_partial_at"] = now
                        log_stage(
                            "asr_first_partial",
                            chunk_id=chunk_id,
                            elapsed_ms=(now - segment_started_at) * 1000,
                            words=len(text.split()),
                        )
                    stable_text = state["stable_tracker"].observe(text, now=now)
                    if stable_text:
                        log_stage(
                            "asr_stable",
                            chunk_id=chunk_id,
                            elapsed_ms=(now - segment_started_at) * 1000,
                            since_first_partial_ms=(now - first_partial_at) * 1000,
                            words=len(stable_text.split()),
                            detail=stable_text,
                        )

            if is_final:
                print(f"[Apple Final {chunk_id}] {text}")
                log_stage(
                    "asr_final",
                    chunk_id=chunk_id,
                    elapsed_ms=(now - segment_started_at) * 1000,
                    since_first_partial_ms=(
                        (now - first_partial_at) * 1000 if first_partial_at else None
                    ),
                    words=len(text.split()),
                    detail=text,
                )
                self.last_final_text = text
                context_text = self._snapshot_finalized_context(text)
                # Preserve the already-visible Apple draft while final translation runs.
                self.signals.update_text.emit(chunk_id, text, "", "final")
                fast_executor.submit(
                    self._run_fast_final_translation,
                    text,
                    chunk_id,
                    refine_executor,
                    context_text,
                    segment_started_at,
                    first_partial_at,
                )
                return

            self.signals.update_text.emit(chunk_id, text, "", "partial")
            with self._translation_state_lock:
                previous = self._last_partial_text.get(chunk_id)
                if previous == text or len(text) < 6:
                    return
                self._last_partial_text[chunk_id] = text
                version = self._partial_versions.get(chunk_id, 0) + 1
                self._partial_versions[chunk_id] = version
            # Speed-first path: every distinct Apple partial is translated. Stable
            # Prefix is measured in parallel and never gates the local draft.
            fast_executor.submit(
                self._run_partial_translation,
                text,
                chunk_id,
                version,
                segment_started_at,
                first_partial_at,
            )

        self.apple_transcriber = AppleSpeechTranscriber(
            language=config.source_language or "en",
            sample_rate=config.sample_rate,
            on_result=on_result,
        )

        try:
            print("[Pipeline] Starting Apple SpeechTranscriber...")
            self.apple_transcriber.start()
            print("[Pipeline] Apple SpeechTranscriber ready")
            for audio_chunk in self.audio.generator():
                if not self.running:
                    break
                audio_marker = None
                with state_lock:
                    if state["audio_started_at"] is None:
                        state["audio_started_at"] = time.monotonic()
                        audio_marker = (state["chunk_id"], state["audio_started_at"])
                if audio_marker:
                    log_stage("audio_received", chunk_id=audio_marker[0], elapsed_ms=0)
                self.apple_transcriber.feed(audio_chunk)
        except Exception as exc:
            print(f"[Pipeline] Apple Speech error: {exc}")
            log_stage("apple_speech", status="error", detail=str(exc))
            self.signals.pipeline_error.emit(str(exc))
        finally:
            if self.apple_transcriber:
                self.apple_transcriber.stop()
            fast_executor.shutdown(wait=False, cancel_futures=True)
            refine_executor.shutdown(wait=False, cancel_futures=True)

    def _process_partial_chunk(self, audio_data, chunk_id, prompt="", translate_executor=None):
        """Transcribe and translate an in-progress utterance."""
        try:
            # Use accumulated context as prompt
            text = self.transcriber.transcribe(audio_data, prompt=prompt)
            if text:
                normalized = " ".join(text.split())
                with self._translation_state_lock:
                    if chunk_id in self._finalized_chunks:
                        return
                    previous = self._last_partial_text.get(chunk_id)
                    # Avoid paying for identical/near-empty partial hypotheses.
                    if normalized == previous or len(normalized) < 6:
                        return
                    self._last_partial_text[chunk_id] = normalized
                    version = self._partial_versions.get(chunk_id, 0) + 1
                    self._partial_versions[chunk_id] = version
                self.signals.update_text.emit(chunk_id, text, "", "partial")
                if translate_executor:
                    translate_executor.submit(
                        self._run_partial_translation,
                        text,
                        chunk_id,
                        version
                    )
        except Exception as e:
            print(f"[Partial {chunk_id}] Error: {e}")

    def _process_final_chunk(self, audio_data, chunk_id, prompt="", translate_executor=None):
        """Transcribe, Log, and Trigger Translation Async"""
        try:
            text = self.transcriber.transcribe(audio_data, prompt=prompt)
            if text:
                print(f"[Final {chunk_id}] Transcribed: {text}")
                context_text = self._snapshot_finalized_context(text)
                # Save for context (only if meaningful)
                if len(text.split()) > 2:
                    self.last_final_text = text
                
                # Emit final transcription first (confirms text)
                self.signals.update_text.emit(chunk_id, text, "(translating...)", "final")
                
                # Offload translation to separate thread so we don't block next transcription
                if translate_executor:
                    self._submit_latest_ai(
                        translate_executor,
                        self._run_translation,
                        text,
                        chunk_id,
                        context_text,
                    )
            else:
                pass
        except Exception as e:
            print(f"[Final {chunk_id}] Error: {e}")

    def _run_partial_translation(
        self,
        text,
        chunk_id,
        version,
        segment_started_at=None,
        first_partial_at=None,
    ):
        """Stream a partial translation while ignoring superseded hypotheses."""
        try:
            if not self.running:
                return
            # Partial jobs can queue behind one another. Drop obsolete work before
            # translation so finalized speech is never delayed by stale drafts.
            with self._translation_state_lock:
                if (self._partial_versions.get(chunk_id) != version or
                        chunk_id in self._finalized_chunks):
                    return
            def emit_if_current(partial):
                with self._translation_state_lock:
                    current = self._partial_versions.get(chunk_id) == version
                    current = current and chunk_id not in self._finalized_chunks
                if current:
                    self.signals.update_text.emit(chunk_id, text, partial, "partial")

            draft = None
            if self.fast_translator:
                try:
                    started = time.perf_counter()
                    draft = self.fast_translator.translate(text)
                    log_stage(
                        "apple_partial",
                        chunk_id=chunk_id,
                        elapsed_ms=(time.perf_counter() - started) * 1000,
                        e2e_ms=(
                            (time.monotonic() - segment_started_at) * 1000
                            if segment_started_at else None
                        ),
                        since_first_partial_ms=(
                            (time.monotonic() - first_partial_at) * 1000
                            if first_partial_at else None
                        ),
                        words=len(text.split()),
                    )
                    emit_if_current(draft)
                except Exception as exc:
                    print(f"[Apple Partial Translation {chunk_id}] Failed: {exc}")
                    log_stage("apple_partial", chunk_id=chunk_id, status="error", detail=str(exc))

            # Remote AI never receives volatile ASR hypotheses. If Apple
            # Translation is unavailable, wait for finalized ASR instead.
            return
        except Exception as e:
            print(f"[Partial Translation {chunk_id}] Failed: {e}")
            log_stage("partial_translation", chunk_id=chunk_id, status="error", detail=str(e))

    def _snapshot_finalized_context(self, text):
        """Return the previous finalized sentence and advance context atomically."""
        with self._context_lock:
            previous = self._last_finalized_segment
            self._last_finalized_segment = text
        return previous

    def _forget_refinement(self, future):
        with self._refine_queue_lock:
            self._refine_futures.pop(future, None)

    def _submit_latest_ai(self, executor, worker, text, chunk_id, context_text):
        """Keep two active AI jobs and at most one latest pending job."""
        deadline = time.monotonic() + config.ai_deadline_seconds
        with self._refine_queue_lock:
            finished = [future for future in self._refine_futures if future.done()]
            for future in finished:
                self._refine_futures.pop(future, None)

            # ThreadPoolExecutor has two workers. Any non-running future is the
            # single pending slot; replace it so the newest classroom sentence wins.
            pending = [
                (future, metadata)
                for future, metadata in self._refine_futures.items()
                if not future.running()
            ]
            for future, metadata in pending:
                if future.cancel():
                    self._refine_futures.pop(future, None)
                    log_stage(
                        "llm_refine",
                        chunk_id=metadata["chunk_id"],
                        status="dropped",
                        detail="replaced by newer finalized segment",
                    )

            future = executor.submit(
                worker, text, chunk_id, context_text, deadline
            )
            self._refine_futures[future] = {
                "chunk_id": chunk_id,
                "deadline": deadline,
            }
        future.add_done_callback(self._forget_refinement)

    def _run_fast_final_translation(
        self,
        text,
        chunk_id,
        refine_executor,
        context_text,
        segment_started_at=None,
        first_partial_at=None,
    ):
        """Publish the local draft immediately, then schedule best-effort refinement."""
        if not self.running:
            return
        draft = None
        if self.fast_translator:
            try:
                started = time.perf_counter()
                draft = self.fast_translator.translate(text)
                elapsed_ms = (time.perf_counter() - started) * 1000
                self._emit_ranked_translation(chunk_id, text, draft, "final", 1)
                log_stage(
                    "apple_final",
                    chunk_id=chunk_id,
                    elapsed_ms=elapsed_ms,
                    e2e_ms=(
                        (time.monotonic() - segment_started_at) * 1000
                        if segment_started_at else None
                    ),
                    since_first_partial_ms=(
                        (time.monotonic() - first_partial_at) * 1000
                        if first_partial_at else None
                    ),
                    words=len(text.split()),
                    detail=draft,
                )
            except Exception as exc:
                print(f"[Apple Final Translation {chunk_id}] Failed: {exc}")
                log_stage("apple_final", chunk_id=chunk_id, status="error", detail=str(exc))

        try:
            self._submit_latest_ai(
                refine_executor,
                self._run_refinement,
                text,
                chunk_id,
                context_text,
            )
        except RuntimeError as exc:
            log_stage("llm_refine", chunk_id=chunk_id, status="skipped", detail=str(exc))

        # Groq is the low-latency bridge between the local Apple draft and the
        # higher-quality final model. It never blocks refinement and cannot
        # overwrite a final-model result that arrived first.
        groq_available = (
            isinstance(self.translator, HybridTranslator) and config.groq_api_key
        )
        use_groq, skip_reason = (
            self._groq_bridge_gate.allow(text)
            if groq_available
            else (False, "Groq bridge is not configured")
        )
        if not use_groq:
            log_stage(
                "groq_bridge",
                chunk_id=chunk_id,
                status="skipped",
                words=len(text.split()),
                detail=skip_reason,
            )
        else:
            try:
                started = time.perf_counter()
                bridge_deadline = min(
                    time.monotonic() + 1.0,
                    time.monotonic() + config.ai_deadline_seconds,
                )
                translated = self.translator.translate_only(
                    {"Groq GPT-OSS 20B"},
                    text,
                    use_context=False,
                    remember_context=False,
                    draft_translation=draft,
                    deadline=bridge_deadline,
                )
                if translated and self.running and time.monotonic() < bridge_deadline:
                    emitted = self._emit_ranked_translation(
                        chunk_id, text, translated, "final", 2
                    )
                    log_stage(
                        "groq_bridge",
                        chunk_id=chunk_id,
                        elapsed_ms=(time.perf_counter() - started) * 1000,
                        status="shown" if emitted else "superseded",
                        detail=translated,
                    )
            except Exception as exc:
                log_stage("groq_bridge", chunk_id=chunk_id, status="skipped", detail=str(exc))

    def _run_refinement(self, text, chunk_id, context_text, deadline):
        try:
            if not self.running or time.monotonic() >= deadline:
                log_stage("llm_refine", chunk_id=chunk_id, status="expired")
                return
            started = time.perf_counter()

            def emit_before_deadline(partial):
                if self.running and time.monotonic() < deadline:
                    self._emit_ranked_translation(chunk_id, text, partial, "final", 3)

            translate = self.translator.translate
            translate_args = ()
            if isinstance(self.translator, HybridTranslator):
                translate = self.translator.translate_excluding
                translate_args = ({"Groq GPT-OSS 20B"},)
            translated = translate(
                *translate_args, text, use_context=False, remember_context=False,
                context_text=context_text, deadline=deadline,
                on_update=emit_before_deadline,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            if translated and self.running and time.monotonic() < deadline:
                self._emit_ranked_translation(chunk_id, text, translated, "final", 3)
                log_stage("llm_refine", chunk_id=chunk_id, elapsed_ms=elapsed_ms, detail=translated)
        except TimeoutError as exc:
            print(f"[LLM Refinement {chunk_id}] Deadline exceeded: {exc}")
            log_stage("llm_refine", chunk_id=chunk_id, status="timeout", detail=str(exc))
        except Exception as exc:
            # Keep the Apple draft visible on all remote API failures.
            print(f"[LLM Refinement {chunk_id}] Failed: {exc}")
            log_stage("llm_refine", chunk_id=chunk_id, status="error", detail=str(exc))

    def _run_translation(self, text, chunk_id, context_text, deadline):
        """Run translation in background and emit result"""
        draft = None
        try:
            if not self.running or time.monotonic() >= deadline:
                return
            if self.fast_translator:
                try:
                    draft = self.fast_translator.translate(text)
                    self.signals.update_text.emit(chunk_id, text, draft, "final")
                except Exception as exc:
                    print(f"[Apple Final Translation {chunk_id}] Failed: {exc}")

            def emit_before_deadline(partial):
                if self.running and time.monotonic() < deadline:
                    self.signals.update_text.emit(chunk_id, text, partial, "final")

            translate = self.translator.translate
            translate_args = ()
            if isinstance(self.translator, HybridTranslator):
                translate = self.translator.translate_excluding
                translate_args = ({"Groq GPT-OSS 20B"},)
            translated = translate(
                *translate_args, text, use_context=False, remember_context=False,
                context_text=context_text, deadline=deadline,
                on_update=emit_before_deadline,
            )
            print(f"[Final {chunk_id}] Translated: {translated}")
            if self.running and time.monotonic() < deadline:
                self.signals.update_text.emit(chunk_id, text, translated, "final")
        except TimeoutError as e:
            print(f"[Translation {chunk_id}] Deadline exceeded: {e}")
            log_stage("translation", chunk_id=chunk_id, status="timeout", detail=str(e))
        except Exception as e:
            print(f"[Translation {chunk_id}] Failed: {e}")
            log_stage("translation", chunk_id=chunk_id, status="error", detail=str(e))
            if not draft:
                self.signals.update_text.emit(chunk_id, text, "[Translation Failed]", "final")
    
    def _transcribe_chunk(self, transcriber, audio_chunk, chunk_id):
        """Transcribe a single chunk and log timing"""
        t0 = time.time()
        text = transcriber.transcribe(audio_chunk)
        t1 = time.time()
        print(f"[Chunk {chunk_id}] Transcribed in {t1-t0:.2f}s: {text if text else '(empty)'}")
        return text
    
    def _translate_and_log(self, text, chunk_id=0):
        """Translate text and log result"""
        t0 = time.time()
        translated_text = self.translator.translate(text)
        t1 = time.time()
        print(f"[Chunk {chunk_id}] Translated in {t1-t0:.2f}s: {translated_text}")
        return (text, translated_text)

# Global reference for signal handler
_pipeline = None
_app = None

def signal_handler(sig, frame):
    """Handle Ctrl-C gracefully"""
    print("\n[Main] Ctrl-C received, force killing...")
    os._exit(0)

def start_overlay_session():
    """Start the overlay and pipeline without blocking (for use in Dashboard)"""
    global _pipeline, _app
    
    # Initialize Overlay Window
    if config.display_mode == "notch":
        from native_notch_overlay import NativeNotchOverlay as OverlayClass
    else:
        OverlayClass = OverlayWindow
    overlay_kwargs = dict(
        display_duration=config.display_duration,
        window_width=config.window_width,
        window_height=config.window_height,
        display_mode=config.display_mode,
    )
    if config.display_mode != "notch":
        overlay_kwargs["video_overlay"] = config.device_index == "system"
    window = OverlayClass(**overlay_kwargs)
    window.show()
    
    # Logic
    _pipeline = Pipeline()
    
    # Connect signals
    _pipeline.signals.update_text.connect(window.update_text)
    
    # Start pipeline
    _pipeline.start()
    
    return window, _pipeline

def main():
    global _pipeline, _app
    
    # Set up signal handler for Ctrl-C
    signal.signal(signal.SIGINT, signal_handler)
    
    _app = QApplication.instance()
    if not _app:
        _app = QApplication(sys.argv)
    
    # Start session
    win, pipe = start_overlay_session()
    
    # Timer to let Python interpreter handle signals (Ctrl-C)
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)
    
    try:
        sys.exit(_app.exec())
    except SystemExit:
        pass
    finally:
        if _pipeline:
            _pipeline.stop()

if __name__ == "__main__":
    main()
