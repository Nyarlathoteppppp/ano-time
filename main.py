import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import sys
import signal
import threading
import queue
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from audio_capture import AudioCapture
from system_audio_capture import SystemAudioCapture
from transcriber import Transcriber
from overlay_factory import OverlaySpec, create_overlay
from config import config
from runtime_log import diagnostics_enabled, log_stage
from stable_prefix import StablePrefixTracker
from groq_bridge import GroqBridgeGate
from live_segmenter import IncrementalSegmenter
from glossary import ASRCorrections
from course_profiles import correction_paths
from finalized_text import clean_finalized_text, is_meaningful_final, should_request_remote
from subtitle_event import SubtitleStage
from runtime_performance import RuntimePerformanceSampler
from segment_store import SegmentStore
from fast_path import FastPath
from translation_workflows import build_translation_workflow
from translation_preview import ProgressiveTranslationPreview
from session_settings import SessionSettingsSnapshot, describe_session
from smart_hint import build_smart_hint_scheduler
from translation_context import ContextPolicy


FINAL_CONTEXT_SEGMENTS = 4


def diagnostic_audio_activity_threshold(silence_threshold):
    """Lower VAD threshold used only to anchor latency measurements."""
    return max(0.0001, float(silence_threshold) * 0.35)


def recent_audio_anchor(recent_activity_at, now, max_age=1.5):
    if recent_activity_at is None:
        return None
    return recent_activity_at if now - recent_activity_at <= max_age else None


def effective_streaming_step_size(asr_backend, configured_step):
    """Feed Apple live ASR at most 50 ms of audio without changing other ASR paths."""
    step = max(0.01, float(configured_step))
    return min(step, 0.05) if str(asr_backend).lower() == "apple" else step

class WorkerSignals(QObject):
    subtitle_event = pyqtSignal(object)
    # (chunk_id, original, translated, ASR state: "partial" | "final")
    update_text = pyqtSignal(int, str, str, str)
    pipeline_error = pyqtSignal(str)
    runtime_status = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def emit_subtitle(self, event):
        """Publish typed and legacy forms without adding an event-loop hop."""
        self.subtitle_event.emit(event)
        self.update_text.emit(
            event.segment_id,
            event.original_text,
            event.translated_text,
            event.legacy_state,
        )

class Pipeline(QObject):
    def __init__(self, session_settings=None):
        super().__init__()
        # The global Config can reload when the Dashboard is saved.  Freeze
        # every runtime value before constructing audio, ASR, or translators.
        self.settings = session_settings or SessionSettingsSnapshot.from_config(config)
        settings = self.settings
        self.session_description = describe_session(settings)
        self.signals = WorkerSignals()
        self.running = True
        self._paused = threading.Event()
        self._translation_state_lock = threading.Lock()
        self._partial_versions = {}
        self._last_partial_text = {}
        self._finalized_chunks = set()
        self._subtitle_event_count_lock = threading.Lock()
        self._segment_store = SegmentStore(settings.target_lang)
        self._fast_path = None
        self._preview_service = None
        self._pause_boundary_handler = None
        self._apple_reset_thread = None
        self._subtitle_events_since_sample = 0
        self._performance_sampler = (
            RuntimePerformanceSampler(self._take_subtitle_event_count)
            if settings.diagnostics_enabled
            else None
        )
        self._context_lock = threading.Lock()
        self._finalized_context = deque(maxlen=FINAL_CONTEXT_SEGMENTS)
        self._context_policy = ContextPolicy()
        self._smart_hint_scheduler = build_smart_hint_scheduler(
            settings,
            status_callback=self._on_smart_hint_status,
        )
        self._refine_queue_lock = threading.RLock()
        self._refine_futures = {}
        self._bridge_queue_lock = threading.RLock()
        self._bridge_futures = {}
        self._groq_bridge_gate = GroqBridgeGate(
            max_per_minute=15,
            duplicate_window=30.0,
        )
        self._asr_corrections = ASRCorrections.from_files(
            correction_paths(
                settings.asr_corrections_path,
                getattr(settings, "course_profile_id", ""),
            )
        )
        
        # Print config for debugging
        print("[Pipeline] Session settings captured at Launch")
        
        # Initialize components
        audio_capture_class = (
            SystemAudioCapture if settings.device_index == "system" else AudioCapture
        )
        self.audio = audio_capture_class(
            device_index=settings.device_index,
            sample_rate=settings.sample_rate,
            silence_threshold=settings.silence_threshold,
            silence_duration=settings.silence_duration,
            chunk_duration=settings.chunk_duration,
            max_phrase_duration=settings.max_phrase_duration,
            streaming_mode=settings.streaming_mode,
            streaming_interval=settings.streaming_interval,
            streaming_step_size=effective_streaming_step_size(
                settings.asr_backend, settings.streaming_step_size
            ),
            streaming_overlap=settings.streaming_overlap
        )
        log_stage(
            "audio_backend",
            detail=(
                f"class={audio_capture_class.__name__} "
                f"configured_device={settings.device_index}"
            ),
        )
        
        # Initialize Transcriber
        print(f"[Pipeline] Initializing Transcriber with backend={settings.asr_backend}, device={settings.whisper_device}...")
        
        # Determine model size based on backend
        if settings.asr_backend == "funasr":
            model_size = settings.funasr_model
        else:
            model_size = settings.whisper_model
            
        self.transcriber = None
        self.apple_transcriber = None
        if settings.asr_backend != "apple":
            self.transcriber = Transcriber(
                backend=settings.asr_backend,
                model_size=model_size,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                language=settings.source_language
            )
        
        print(
            "[Pipeline] Initializing translation workflow "
            f"({settings.translation_workflow}, target={settings.target_lang})..."
        )
        self.translation_workflow = build_translation_workflow(
            settings,
            usage_path=os.path.join(
                os.path.dirname(__file__), "logs", "provider_usage.json"
            ),
            status_callback=self._on_provider_status,
        )
        self.final_translator = self.translation_workflow.final_translator
        self.preview_translator = self.translation_workflow.preview_translator
        self.bridge_translator = self.translation_workflow.bridge_translator
        # Compatibility for tests and third-party code using Pipeline.translator.
        self.translator = self.final_translator

        self.fast_translator = None
        self._apple_translation_status = None
        if (
            settings.fast_translation_backend == "apple"
            or settings.translation_workflow == "apple_only"
        ):
            try:
                from apple_translation import AppleTranslator
                self.fast_translator = AppleTranslator(
                    source=settings.source_language,
                    target=settings.target_lang,
                    status_callback=self._on_apple_translation_status,
                )
            except Exception as exc:
                message = f"Apple · unavailable: {exc}"
                self._apple_translation_status = ("error", message)
                print(f"[Pipeline] Apple Translation unavailable, using LLM only: {exc}")
        
        # Warmup Transcriber (Critical for MLX/GPU)
        if self.transcriber:
            self.transcriber.warmup()

    def _on_provider_status(self, status, provider, elapsed_ms=None, detail=""):
        log_stage(
            "provider_attempt", status=status, elapsed_ms=elapsed_ms,
            provider=provider, detail=detail,
        )
        if elapsed_ms is not None:
            message = f"{provider} · {elapsed_ms / 1000:.1f}s"
        elif status == "active":
            message = f"{provider} · translating"
        else:
            message = f"{provider} · {detail or status}"
        self.signals.runtime_status.emit("Remote", status, message)
        network_status = "ok" if status in ("active", "ok") else status
        network_message = "Online" if network_status == "ok" else detail or status
        self.signals.runtime_status.emit("Network", network_status, network_message)

    def _on_apple_translation_status(self, status, message):
        ui_status = "ok" if status == "ready" else (
            "warning" if status == "preparing" else "error"
        )
        self._apple_translation_status = (ui_status, message)
        self.signals.runtime_status.emit("Draft", ui_status, message)

    def _on_smart_hint_status(self, status, detail):
        """Publish independent hint health without affecting translation routing."""
        log_stage("smart_hint", status=status, detail=detail)
        self.signals.runtime_status.emit("Hint", status, detail)

    def _smart_hint_text(self):
        scheduler = self.__dict__.get("_smart_hint_scheduler")
        return scheduler.snapshot() if scheduler is not None else ""

    def _fast_translation_ready(self):
        translator = self.fast_translator
        if not translator:
            return False
        return bool(getattr(translator, "is_ready", True))

    def _final_translation_client(self):
        return self.__dict__.get(
            "final_translator", self.__dict__.get("translator")
        )

    def _bridge_translation_client(self):
        return self.__dict__.get("bridge_translator")

    def _preview_translation_client(self):
        return self.__dict__.get(
            "preview_translator", self._final_translation_client()
        )

    def _final_status_managed(self):
        workflow = self.__dict__.get("translation_workflow")
        return bool(workflow and workflow.final_status_managed)

    def _final_translation_label(self):
        workflow = self.__dict__.get("translation_workflow")
        return workflow.final_label if workflow else self._session_settings().model

    def _session_settings(self):
        """Read the immutable launch snapshot, retaining legacy test support."""
        return self.__dict__.get("settings", config)

    def _emit_ranked_translation(
        self, chunk_id, text, translated, state, rank, stage=None
    ):
        """Prevent a late draft from replacing a newer translation stage."""
        if self._paused.is_set():
            return False
        if stage is None:
            stage = {
                1: SubtitleStage.APPLE_FINAL,
                2: SubtitleStage.GROQ_BRIDGE,
                3: SubtitleStage.AI_FINAL,
            }.get(rank, SubtitleStage.AI_STREAM)
        event = self._emit_subtitle(
            chunk_id,
            text,
            translated,
            state,
            stage,
            translation_rank=rank,
        )
        if event is None:
            return False
        return True

    def _segment_state_store(self):
        store = self.__dict__.get("_segment_store")
        if store is None:
            target_lang = getattr(
                getattr(self, "settings", None), "target_lang", "Chinese"
            )
            store = self._segment_store = SegmentStore(target_lang)
        return store

    def _publish_subtitle_event(self, event):
        if event is None:
            return None
        lock = self.__dict__.get("_subtitle_event_count_lock")
        if lock is None:
            lock = self._subtitle_event_count_lock = threading.Lock()
        with lock:
            if self.__dict__.get("_performance_sampler") is not None:
                self._subtitle_events_since_sample = (
                    self.__dict__.get("_subtitle_events_since_sample", 0) + 1
                )
        adapter = getattr(self.signals, "emit_subtitle", None)
        if adapter is not None:
            adapter(event)
        else:
            # Compatibility for lightweight test doubles and third-party users.
            self.signals.update_text.emit(
                event.segment_id,
                event.original_text,
                event.translated_text,
                event.legacy_state,
            )
        return event

    def _emit_subtitle(
        self,
        chunk_id,
        text,
        translated="",
        state="partial",
        stage=None,
        expected_hypothesis=None,
        translation_rank=None,
        translation_source_text=None,
        committed_prefix_length=None,
    ):
        """Publish one typed event; retain the legacy signal through the adapter."""
        if stage is None:
            if state == "partial":
                stage = (
                    SubtitleStage.APPLE_PARTIAL
                    if translated else SubtitleStage.ASR_PARTIAL
                )
            else:
                stage = SubtitleStage.AI_STREAM if translated else SubtitleStage.ASR_FINAL
        event = self._segment_state_store().publish(
            chunk_id,
            stage,
            text,
            translated,
            finalized=state == "final",
            expected_hypothesis=expected_hypothesis,
            translation_rank=translation_rank,
            translation_source_text=translation_source_text,
            committed_prefix_length=committed_prefix_length,
        )
        return self._publish_subtitle_event(event)

    def _take_subtitle_event_count(self):
        with self._subtitle_event_count_lock:
            count = self._subtitle_events_since_sample
            self._subtitle_events_since_sample = 0
        return count

    def start(self):
        """Start the processing pipeline in a dedicated thread"""
        self._start_remote_warmup()
        # self.audio.start() # DISABLE: Generator manages its own stream. calling this causes double-stream error on macOS
        self.thread = threading.Thread(target=self.processing_loop)
        self.thread.daemon = True
        sampler = self.__dict__.get("_performance_sampler")
        if sampler:
            sampler.start()
        signals = self.__dict__.get("signals")
        apple_status = self.__dict__.get("_apple_translation_status")
        if signals is not None and apple_status:
            signals.runtime_status.emit("Draft", *apple_status)
        if signals is not None:
            if self.__dict__.get("_smart_hint_scheduler") is not None:
                signals.runtime_status.emit("Hint", "waiting", "ON · 4 分钟后开始总结")
            else:
                signals.runtime_status.emit("Hint", "off", "OFF")
        self.thread.start()

    def _start_remote_warmup(self):
        """Warm paid Gemini in the background; never delay Pipeline startup."""
        workflow = self.__dict__.get("translation_workflow")
        translator = getattr(workflow, "warmup_translator", None)
        if translator is None or not hasattr(translator, "warmup"):
            return None
        existing = self.__dict__.get("_remote_warmup_thread")
        if existing is not None and existing.is_alive():
            return existing

        def run():
            started = time.perf_counter()
            try:
                warmed = translator.warmup()
                log_stage(
                    "gemini_warmup",
                    status="ok" if warmed else "skipped",
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                )
            except Exception as exc:
                # Warmup is optional and must never cool down, switch models,
                # update subtitles, or fail session startup.
                log_stage(
                    "gemini_warmup",
                    status="error",
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    detail=str(exc),
                )

        thread = threading.Thread(
            target=run,
            name="gemini-background-warmup",
            daemon=True,
        )
        self._remote_warmup_thread = thread
        thread.start()
        return thread

    def stop(self):
        print("\n[Pipeline] Stopping...")
        self.running = False
        preview_service = self.__dict__.get("_preview_service")
        if preview_service:
            preview_service.reset()
        smart_hint_scheduler = self.__dict__.get("_smart_hint_scheduler")
        if smart_hint_scheduler:
            smart_hint_scheduler.shutdown()
        self.audio.stop()
        if hasattr(self, "thread") and self.thread.is_alive():
            self.thread.join(timeout=2)
        if self.fast_translator:
            self.fast_translator.stop()
        fast_path = self.__dict__.get("_fast_path")
        if fast_path:
            fast_path.shutdown(wait=False)
        sampler = self.__dict__.get("_performance_sampler")
        if sampler:
            sampler.stop()
        print("[Pipeline] Stopped.")

    def set_paused(self, paused):
        """Pause audio ingestion without tearing down capture permissions."""
        if paused:
            self._paused.set()
            self._clear_finalized_context()
            fast_path = self.__dict__.get("_fast_path")
            if fast_path:
                fast_path.invalidate_all()
            boundary_handler = self.__dict__.get("_pause_boundary_handler")
            if boundary_handler:
                boundary_handler()
            apple_transcriber = self.__dict__.get("apple_transcriber")
            reset_thread = self.__dict__.get("_apple_reset_thread")
            if (
                apple_transcriber is not None
                and (reset_thread is None or not reset_thread.is_alive())
            ):
                reset_thread = threading.Thread(
                    target=apple_transcriber.reset,
                    name="apple-speech-pause-reset",
                    daemon=True,
                )
                self._apple_reset_thread = reset_thread
                reset_thread.start()
            print("[Pipeline] Paused.")
        else:
            # Clear again on resume: a final callback already in flight when
            # pause began may have appended after the first reset.
            self._clear_finalized_context()
            self._paused.clear()
            print("[Pipeline] Resumed.")

    def _clear_finalized_context(self):
        context = self.__dict__.get("_finalized_context")
        lock = self.__dict__.get("_context_lock")
        if context is None or lock is None:
            return
        with lock:
            context.clear()

    @property
    def is_paused(self):
        return self._paused.is_set()

    def processing_loop(self):
        """Fully parallel pipeline: multiple concurrent transcription + translation"""
        settings = self._session_settings()
        if settings.asr_backend == "apple":
            self._processing_loop_apple()
            return

        print("Pipeline processing loop started (FULLY PARALLEL mode).")
        
        # Create multiple transcribers for concurrent processing
        # CHECK: If using MLX, force 1 worker (MLX is not thread-safe for parallel inference in this way)
        is_mlx = (settings.asr_backend == "mlx")
        
        if is_mlx:
            print("[Pipeline] MLX backend detected - forcing single worker (MLX uses GPU parallelism internaly)")
            num_transcription_workers = 1
        else:
            num_transcription_workers = settings.transcription_workers
            
        print(f"[Pipeline] Using {num_transcription_workers} transcription workers...")
        
        # Determine model size based on backend
        if settings.asr_backend == "funasr":
            model_size = settings.funasr_model
        else:
            model_size = settings.whisper_model
        
        transcribers = [self.transcriber]  # Reuse existing one
        for i in range(num_transcription_workers - 1):
            t = Transcriber(
                backend=settings.asr_backend,
                model_size=model_size,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                language=settings.source_language
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
                if self._paused.is_set():
                    buffer = np.array([], dtype=np.float32)
                    phrase_start_time = time.time()
                    last_update_time = phrase_start_time
                    continue
                buffer = np.concatenate([buffer, audio_chunk])
                now = time.time()
                buffer_duration = len(buffer) / self.audio.sample_rate
                
                # Check silence for finalization
                # Use configured silence duration/threshold
                is_silence = False
                min_silence_dur = settings.silence_duration # e.g. 1.0s
                
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
                elif now - last_update_time > settings.update_interval and buffer_duration > 0.5:
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
        settings = self._session_settings()

        # Apple drafts are the latency-critical path. Never run network work on
        # this executor: a slow bridge request would otherwise delay every new
        # provisional subtitle behind it.
        fast_path = (
            FastPath(self._segment_state_store())
            if settings.split_fast_path
            else None
        )
        self._fast_path = fast_path
        fast_executor = None if fast_path else ThreadPoolExecutor(max_workers=1)
        bridge_executor = ThreadPoolExecutor(max_workers=1)
        refine_executor = ThreadPoolExecutor(max_workers=2)
        preview_service = ProgressiveTranslationPreview(
            emit_subtitle=self._emit_subtitle,
            segment_store=self._segment_state_store(),
            bridge_client=self._bridge_translation_client,
            final_client=self._preview_translation_client,
            bridge_gate=self._groq_bridge_gate,
            context_snapshot=self._preview_context_policy_snapshot,
            is_active=lambda: self.running and not self._paused.is_set(),
            hint_snapshot=self._smart_hint_text,
            status_callback=lambda status, detail: self.signals.runtime_status.emit(
                "Preview", status, detail
            ),
        )
        self._preview_service = preview_service
        self.signals.runtime_status.emit(
            "Preview",
            "ok" if self._final_translation_client() is not None else "warning",
            "ON · waiting" if self._final_translation_client() is not None else "OFF",
        )
        state_lock = threading.Lock()
        state = {
            "chunk_id": 1,
            "audio_started_at": None,
            "recent_audio_activity_at": None,
            "first_partial_at": None,
            "stable_tracker": StablePrefixTracker(
                agreement_window=settings.stable_prefix_window,
                min_growth_words=settings.stable_prefix_min_words,
            ),
            "segmenter": IncrementalSegmenter(),
            "stream_ready_logged": False,
            "latest_remainder": "",
        }

        def seal_pause_boundary():
            """Finalize/discard the current hypothesis and force a new ID."""
            boundary = None
            with state_lock:
                remainder = state["latest_remainder"]
                had_activity = bool(
                    remainder
                    or state["audio_started_at"] is not None
                    or state["first_partial_at"] is not None
                )
                if remainder and is_meaningful_final(remainder):
                    boundary = (state["chunk_id"], remainder)
                if had_activity:
                    state["chunk_id"] += 1
                state["audio_started_at"] = None
                state["recent_audio_activity_at"] = None
                state["first_partial_at"] = None
                state["stable_tracker"] = StablePrefixTracker(
                    agreement_window=settings.stable_prefix_window,
                    min_growth_words=settings.stable_prefix_min_words,
                )
                state["segmenter"] = IncrementalSegmenter()
                state["latest_remainder"] = ""
            if boundary:
                chunk_id, text = boundary
                with self._translation_state_lock:
                    self._finalized_chunks.add(chunk_id)
                    self._partial_versions[chunk_id] = (
                        self._partial_versions.get(chunk_id, 0) + 1
                    )
                self._emit_subtitle(
                    chunk_id, text, "", "final", SubtitleStage.ASR_FINAL
                )
                log_stage(
                    "pause_boundary", chunk_id=chunk_id,
                    status="sealed", detail=text,
                )
            else:
                log_stage("pause_boundary", status="reset")
            preview_service.reset()

        self._pause_boundary_handler = seal_pause_boundary

        def publish_final(text, chunk_id, segment_started_at, first_partial_at,
                          cut_reason="native_final"):
            original_text = text
            text = clean_finalized_text(self._asr_corrections.apply(text))
            if text != original_text:
                log_stage(
                    "final_text_cleanup", chunk_id=chunk_id,
                    detail=f"{original_text} -> {text}",
                )
            if not is_meaningful_final(text):
                log_stage(
                    "asr_final", chunk_id=chunk_id, status="filtered",
                    cut_reason=cut_reason, detail=original_text,
                )
                return
            now = time.monotonic()
            with self._translation_state_lock:
                self._finalized_chunks.add(chunk_id)
                self._partial_versions[chunk_id] = self._partial_versions.get(chunk_id, 0) + 1
            elapsed_ms = (now - segment_started_at) * 1000
            print(f"[Apple Final {chunk_id}] {text}")
            log_stage(
                "asr_final", chunk_id=chunk_id, elapsed_ms=elapsed_ms,
                since_first_partial_ms=(
                    (now - first_partial_at) * 1000 if first_partial_at else None
                ),
                words=len(text.split()), cut_reason=cut_reason, detail=text,
            )
            self.signals.runtime_status.emit(
                "ASR", "ok", f"Apple · {elapsed_ms / 1000:.1f}s"
            )
            self.last_final_text = text
            previous_preview = preview_service.displayed_candidate(chunk_id)
            final_context = self._snapshot_finalized_context(
                text,
                limit=3,
                previous_preview=previous_preview,
            )
            log_stage(
                "translation_context",
                chunk_id=chunk_id,
                stage_name="final",
                context_tokens=final_context.estimated_tokens,
                truncated=final_context.truncated,
            )
            self._emit_subtitle(
                chunk_id, text, "", "final", SubtitleStage.ASR_FINAL
            )
            preview_service.finalize(chunk_id)
            self._schedule_final_remote(
                text,
                chunk_id,
                bridge_executor,
                refine_executor,
                final_context,
            )
            final_args = (
                text, chunk_id, segment_started_at, first_partial_at,
            )
            if fast_path:
                fast_path.submit_final(
                    chunk_id, self._run_fast_final_translation, *final_args
                )
            else:
                fast_executor.submit(
                    self._run_fast_final_translation, *final_args
                )

        def on_result(text, is_final):
            if not self.running or self._paused.is_set():
                return
            text = " ".join(text.split())
            if not text:
                return
            now = time.monotonic()
            finalized_segments = []
            preview_stable_text = ""
            with state_lock:
                audio_anchor = state["audio_started_at"]
                if audio_anchor is None:
                    recent_audio = recent_audio_anchor(
                        state["recent_audio_activity_at"], now
                    )
                    if recent_audio is not None:
                        audio_anchor = recent_audio
                        state["audio_started_at"] = recent_audio
                segment_started_at = audio_anchor or now
                first_partial_at = state["first_partial_at"]
                stable_text = text if is_final else ""
                if not is_final:
                    if first_partial_at is None:
                        first_partial_at = now
                        state["first_partial_at"] = now
                        self.signals.runtime_status.emit(
                            "ASR", "active", "Apple · listening"
                        )
                        log_stage(
                            "asr_first_partial",
                            chunk_id=state["chunk_id"],
                            status="ok" if audio_anchor else "unanchored",
                            elapsed_ms=(
                                (now - segment_started_at) * 1000
                                if audio_anchor else None
                            ),
                            words=len(text.split()),
                        )
                    stable_text = state["stable_tracker"].observe(text, now=now)
                    if stable_text:
                        log_stage(
                            "asr_stable",
                            chunk_id=state["chunk_id"],
                            elapsed_ms=(now - segment_started_at) * 1000,
                            since_first_partial_ms=(now - first_partial_at) * 1000,
                            words=len(stable_text.split()),
                            detail=stable_text,
                        )
                segments, remainder = state["segmenter"].observe(
                    text, stable_text=stable_text, is_final=is_final, now=now
                )
                state["latest_remainder"] = "" if is_final else remainder
                if not is_final and stable_text and remainder:
                    stable_word_count = len(stable_text.split())
                    committed_word_count = state["segmenter"].committed_words
                    stable_remainder_count = max(
                        0, stable_word_count - committed_word_count
                    )
                    preview_stable_text = " ".join(
                        remainder.split()[:stable_remainder_count]
                    )
                cut_reasons = list(state["segmenter"].last_cut_reasons)
                for index, segment in enumerate(segments):
                    finalized_segments.append((
                        state["chunk_id"], segment,
                        segment_started_at, first_partial_at,
                        cut_reasons[index] if index < len(cut_reasons) else "unknown",
                    ))
                    state["chunk_id"] += 1
                    segment_started_at = now
                    first_partial_at = now
                current_chunk_id = state["chunk_id"]
                if is_final:
                    state["audio_started_at"] = None
                    state["first_partial_at"] = None
                    state["stable_tracker"] = StablePrefixTracker(
                        agreement_window=settings.stable_prefix_window,
                        min_growth_words=settings.stable_prefix_min_words,
                    )
                elif finalized_segments:
                    state["audio_started_at"] = now
                    state["first_partial_at"] = now

            for final_id, segment, started_at, partial_at, cut_reason in finalized_segments:
                publish_final(segment, final_id, started_at, partial_at, cut_reason)

            if is_final:
                self.signals.runtime_status.emit("ASR", "ok", "Apple · idle")
                return

            if not remainder:
                return
            if not is_meaningful_final(remainder):
                return
            prior_state = self._segment_state_store().snapshot(current_chunk_id)
            event = self._emit_subtitle(
                current_chunk_id,
                remainder,
                "",
                "partial",
                SubtitleStage.ASR_PARTIAL,
            )
            if event is None:
                return
            preview_service.reset_if_source_rewritten(
                current_chunk_id,
                prior_state,
                remainder,
            )
            with self._translation_state_lock:
                previous = self._last_partial_text.get(current_chunk_id)
                if previous == remainder:
                    return
                self._last_partial_text[current_chunk_id] = remainder
                hypothesis_revision = (
                    self._segment_state_store().hypothesis_revision(
                        current_chunk_id
                    )
                )
                if fast_path:
                    version = hypothesis_revision
                else:
                    version = self._partial_versions.get(current_chunk_id, 0) + 1
                self._partial_versions[current_chunk_id] = version
            preview_service.observe(
                current_chunk_id,
                hypothesis_revision,
                remainder,
                stable_source_text=preview_stable_text,
            )
            # Speed-first path: every distinct Apple partial is translated. Stable
            # Prefix is measured in parallel and never gates the local draft.
            partial_args = (
                remainder, current_chunk_id, version,
                segment_started_at, first_partial_at,
            )
            if fast_path:
                fast_path.submit_partial(
                    current_chunk_id,
                    version,
                    self._run_partial_translation,
                    *partial_args,
                )
            else:
                fast_executor.submit(
                    self._run_partial_translation, *partial_args
                )

        self.apple_transcriber = AppleSpeechTranscriber(
            language=settings.source_language or "en",
            sample_rate=settings.sample_rate,
            on_result=on_result,
        )

        try:
            print("[Pipeline] Starting Apple SpeechTranscriber...")
            self.apple_transcriber.start()
            print("[Pipeline] Apple SpeechTranscriber ready")
            for audio_chunk in self.audio.generator():
                if not self.running:
                    break
                if self._paused.is_set():
                    continue
                audio_marker = None
                with state_lock:
                    if not state["stream_ready_logged"]:
                        state["stream_ready_logged"] = True
                        log_stage("audio_stream_ready", elapsed_ms=0)
                    rms = float((audio_chunk ** 2).mean() ** 0.5)
                    # Diagnostic anchor only: Apple Speech can recognize quiet
                    # speech below the user-facing silence threshold. A lower
                    # threshold makes first-partial latency measurable without
                    # changing which audio is fed to ASR.
                    activity_threshold = diagnostic_audio_activity_threshold(
                        settings.silence_threshold
                    )
                    if rms >= activity_threshold:
                        state["recent_audio_activity_at"] = time.monotonic()
                    if (
                        state["audio_started_at"] is None
                        and rms >= activity_threshold
                    ):
                        state["audio_started_at"] = time.monotonic()
                        audio_marker = (state["chunk_id"], state["audio_started_at"])
                if audio_marker:
                    self.signals.runtime_status.emit(
                        "ASR", "waiting", "Apple · audio detected"
                    )
                    log_stage(
                        "speech_audio_detected",
                        chunk_id=audio_marker[0],
                        elapsed_ms=0,
                        rms=f"{rms:.5f}",
                    )
                self.apple_transcriber.feed(audio_chunk)
        except Exception as exc:
            print(f"[Pipeline] Apple Speech error: {exc}")
            log_stage("apple_speech", status="error", detail=str(exc))
            self.signals.pipeline_error.emit(str(exc))
        finally:
            if self.apple_transcriber:
                self.apple_transcriber.stop()
            if fast_path:
                fast_path.shutdown(wait=False)
            elif fast_executor:
                fast_executor.shutdown(wait=False, cancel_futures=True)
            if self.__dict__.get("_fast_path") is fast_path:
                self._fast_path = None
            self._pause_boundary_handler = None
            bridge_executor.shutdown(wait=False, cancel_futures=True)
            refine_executor.shutdown(wait=False, cancel_futures=True)
            preview_service.shutdown()
            if self.__dict__.get("_preview_service") is preview_service:
                self._preview_service = None

    def _process_partial_chunk(self, audio_data, chunk_id, prompt="", translate_executor=None):
        """Transcribe and translate an in-progress utterance."""
        try:
            if self._paused.is_set():
                return
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
                self._emit_subtitle(
                    chunk_id, text, "", "partial", SubtitleStage.ASR_PARTIAL
                )
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
            if self._paused.is_set():
                return
            text = self.transcriber.transcribe(audio_data, prompt=prompt)
            if text:
                original_text = text
                text = clean_finalized_text(self._asr_corrections.apply(text))
                if text != original_text:
                    log_stage(
                        "asr_correction", chunk_id=chunk_id,
                        detail=f"{original_text} -> {text}",
                    )
                if not is_meaningful_final(text):
                    log_stage(
                        "asr_final", chunk_id=chunk_id, status="filtered",
                        detail=original_text,
                    )
                    return
                print(f"[Final {chunk_id}] Transcribed: {text}")
                context = self._snapshot_finalized_context(text)
                # Save for context (only if meaningful)
                if len(text.split()) > 2:
                    self.last_final_text = text
                
                # Emit final transcription first (confirms text)
                self._emit_subtitle(
                    chunk_id,
                    text,
                    "(translating...)",
                    "final",
                    SubtitleStage.ASR_FINAL,
                )
                
                # Offload translation to separate thread so we don't block next transcription
                if translate_executor:
                    self._submit_latest_ai(
                        translate_executor,
                        self._run_translation,
                        text,
                        chunk_id,
                        context,
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
        """Translate every distinct partial and reject only stale UI writes."""
        try:
            if not self.running:
                return
            fast_path = self.__dict__.get("_fast_path")
            if not fast_path:
                with self._translation_state_lock:
                    if (self._partial_versions.get(chunk_id) != version or
                            chunk_id in self._finalized_chunks):
                        return
            def emit_if_current(partial):
                if fast_path:
                    current = self._segment_state_store().partial_is_compatible(
                        chunk_id, version, text
                    )
                    current = current and not self._paused.is_set()
                else:
                    with self._translation_state_lock:
                        current = self._partial_versions.get(chunk_id) == version
                        current = current and chunk_id not in self._finalized_chunks
                        current = current and not self._paused.is_set()
                if current:
                    return bool(self._emit_subtitle(
                        chunk_id,
                        text,
                        partial,
                        "partial",
                        SubtitleStage.APPLE_PARTIAL,
                        expected_hypothesis=(version if fast_path else None),
                    ))
                return False

            draft = None
            if self._fast_translation_ready():
                try:
                    self.signals.runtime_status.emit(
                        "Draft", "active", "Apple · translating"
                    )
                    started = time.perf_counter()
                    draft = self.fast_translator.translate(text)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    shown = emit_if_current(draft)
                    log_stage(
                        "apple_partial",
                        chunk_id=chunk_id,
                        elapsed_ms=elapsed_ms,
                        status="shown" if shown else "dropped_stale",
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
                    self.signals.runtime_status.emit(
                        "Draft", "ok", f"Apple · {elapsed_ms / 1000:.1f}s"
                    )
                except Exception as exc:
                    self.signals.runtime_status.emit(
                        "Draft", "error", f"Apple · {exc}"
                    )
                    print(f"[Apple Partial Translation {chunk_id}] Failed: {exc}")
                    log_stage("apple_partial", chunk_id=chunk_id, status="error", detail=str(exc))

            # Remote AI never receives volatile ASR hypotheses. If Apple
            # Translation is unavailable, wait for finalized ASR instead.
            return
        except Exception as e:
            print(f"[Partial Translation {chunk_id}] Failed: {e}")
            log_stage("partial_translation", chunk_id=chunk_id, status="error", detail=str(e))

    def _snapshot_finalized_context(self, text, limit=3, previous_preview=""):
        """Freeze bounded prior finalized context, then append current text."""
        limit = max(0, int(limit))
        with self._context_lock:
            history = tuple(self._finalized_context)
            self._finalized_context.append(text)
        scheduler = self.__dict__.get("_smart_hint_scheduler")
        if scheduler is not None:
            # The scheduler only copies finalized source into a bounded deque;
            # its optional request is submitted on its own executor.
            scheduler.observe_finalized(text)
        policy = self.__dict__.get("_context_policy") or ContextPolicy()
        return policy.final(
            history,
            previous_preview=previous_preview,
            live_hint=self._smart_hint_text(),
            history_limit=limit,
        )

    def _current_finalized_context(self, limit=1):
        """Read prior finalized context without appending a provisional prefix."""
        limit = max(0, int(limit))
        with self._context_lock:
            return (
                "\n".join(list(self._finalized_context)[-limit:])
                if limit else ""
            )

    def _preview_context_policy_snapshot(self):
        """Return a frozen history snapshot for a Preview trigger."""
        with self._context_lock:
            history = tuple(self._finalized_context)
        policy = self.__dict__.get("_context_policy") or ContextPolicy()

        class PreviewContextFactory:
            def first_preview(_self):
                context = policy.first_preview(
                    history,
                    live_hint=self._smart_hint_text(),
                )
                log_stage(
                    "translation_context",
                    stage_name="preview_first",
                    context_tokens=context.estimated_tokens,
                    truncated=context.truncated,
                )
                return context

            def continuing_preview(_self, *, previous_preview=""):
                context = policy.continuing_preview(
                    history,
                    previous_preview=previous_preview,
                    live_hint=self._smart_hint_text(),
                )
                log_stage(
                    "translation_context",
                    stage_name="preview",
                    context_tokens=context.estimated_tokens,
                    truncated=context.truncated,
                )
                return context

            def bridge(_self):
                context = policy.bridge(live_hint=self._smart_hint_text())
                log_stage(
                    "translation_context",
                    stage_name="bridge",
                    context_tokens=context.estimated_tokens,
                    truncated=context.truncated,
                )
                return context

        return PreviewContextFactory()

    def _forget_refinement(self, future):
        with self._refine_queue_lock:
            self._refine_futures.pop(future, None)

    def _forget_bridge(self, future):
        with self._bridge_queue_lock:
            self._bridge_futures.pop(future, None)

    def _submit_latest_bridge(self, executor, text, chunk_id, draft, context=None):
        """Run one Groq bridge request and retain only the latest pending one."""
        deadline = time.monotonic() + 1.0
        with self._bridge_queue_lock:
            finished = [future for future in self._bridge_futures if future.done()]
            for future in finished:
                self._bridge_futures.pop(future, None)
            for future, metadata in list(self._bridge_futures.items()):
                if not future.running() and future.cancel():
                    self._bridge_futures.pop(future, None)
                    log_stage(
                        "groq_bridge",
                        chunk_id=metadata["chunk_id"],
                        status="dropped",
                        detail="replaced by newer finalized segment",
                    )
            args = (text, chunk_id, draft, deadline)
            if context is not None:
                args += (context,)
            future = executor.submit(self._run_groq_bridge, *args)
            self._bridge_futures[future] = {
                "chunk_id": chunk_id,
                "deadline": deadline,
            }
        future.add_done_callback(self._forget_bridge)

    def _submit_latest_ai(
        self, executor, worker, text, chunk_id, context,
        previous_preview="",
    ):
        """Keep two active AI jobs and at most one latest pending job."""
        submitted_at = time.monotonic()
        deadline = submitted_at + self._session_settings().ai_deadline_seconds
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

            kwargs = {"submitted_at": submitted_at}
            if previous_preview:
                kwargs["previous_preview"] = previous_preview
            future = executor.submit(worker, text, chunk_id, context, deadline, **kwargs)
            self._refine_futures[future] = {
                "chunk_id": chunk_id,
                "deadline": deadline,
            }
        future.add_done_callback(self._forget_refinement)

    def _schedule_final_remote(
        self,
        text,
        chunk_id,
        bridge_executor,
        refine_executor,
        context,
    ):
        """Submit network finalization without entering the Apple work queue."""
        paused = self.__dict__.get("_paused")
        if not self.running or (paused is not None and paused.is_set()):
            return
        if not should_request_remote(text):
            log_stage(
                "remote_refine", chunk_id=chunk_id, status="skipped",
                words=len(text.split()), detail="short or low-value final",
            )
            return

        try:
            if self._final_translation_client() is None:
                raise RuntimeError("final model is off")
            self._submit_latest_ai(
                refine_executor,
                self._run_refinement,
                text,
                chunk_id,
                context,
            )
        except RuntimeError as exc:
            log_stage("llm_refine", chunk_id=chunk_id, status="skipped", detail=str(exc))

        try:
            if self._bridge_translation_client() is None:
                raise RuntimeError("bridge is off")
            policy = self.__dict__.get("_context_policy") or ContextPolicy()
            bridge_context = policy.bridge(live_hint=self._smart_hint_text())
            self._submit_latest_bridge(
                bridge_executor, text, chunk_id, None, bridge_context
            )
        except RuntimeError as exc:
            log_stage("groq_bridge", chunk_id=chunk_id, status="skipped", detail=str(exc))

    def _run_fast_final_translation(
        self,
        text,
        chunk_id,
        segment_started_at=None,
        first_partial_at=None,
    ):
        """Publish Apple final independently of already-scheduled network work."""
        paused = self.__dict__.get("_paused")
        if not self.running or (paused is not None and paused.is_set()):
            return
        draft = None
        if self._fast_translation_ready():
            try:
                self.signals.runtime_status.emit(
                    "Draft", "active", "Apple · translating"
                )
                started = time.perf_counter()
                draft = self.fast_translator.translate(text)
                elapsed_ms = (time.perf_counter() - started) * 1000
                self._emit_ranked_translation(chunk_id, text, draft, "final", 1)
                self.signals.runtime_status.emit(
                    "Draft", "ok", f"Apple · {elapsed_ms / 1000:.1f}s"
                )
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
                self.signals.runtime_status.emit(
                    "Draft", "error", f"Apple · {exc}"
                )
                print(f"[Apple Final Translation {chunk_id}] Failed: {exc}")
                log_stage("apple_final", chunk_id=chunk_id, status="error", detail=str(exc))

        if paused is not None and paused.is_set():
            return

    def _run_groq_bridge(self, text, chunk_id, draft, deadline, context=None):
        """Best-effort bridge isolated from Apple drafts and final refinement."""
        if not self.running or time.monotonic() >= deadline:
            log_stage("groq_bridge", chunk_id=chunk_id, status="expired")
            return
        # Groq cannot overwrite a final-model result that arrived first.
        bridge_translator = self._bridge_translation_client()
        groq_available = bridge_translator is not None
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
                    deadline,
                    time.monotonic() + self._session_settings().ai_deadline_seconds,
                )
                translated = bridge_translator.translate(
                    text,
                    use_context=False,
                    remember_context=False,
                    draft_translation=draft,
                    live_hint=(context.live_hint if context else self._smart_hint_text()),
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

    def _run_refinement(
        self,
        text,
        chunk_id,
        context,
        deadline,
        previous_preview="",
        submitted_at=None,
    ):
        try:
            queue_wait_ms = (
                (time.monotonic() - submitted_at) * 1000
                if submitted_at is not None else 0.0
            )
            log_stage(
                "final_queue_wait",
                chunk_id=chunk_id,
                elapsed_ms=queue_wait_ms,
            )
            paused = self.__dict__.get("_paused")
            if (
                not self.running
                or (paused is not None and paused.is_set())
                or time.monotonic() >= deadline
            ):
                log_stage("llm_refine", chunk_id=chunk_id, status="expired")
                return
            started = time.perf_counter()

            context = self._normalise_translation_context(
                context, previous_preview=previous_preview
            )

            def emit_before_deadline(partial):
                if (
                    not context.previous_preview
                    and self.running
                    and (paused is None or not paused.is_set())
                    and time.monotonic() < deadline
                ):
                    self._emit_ranked_translation(
                        chunk_id,
                        text,
                        partial,
                        "final",
                        3,
                        SubtitleStage.AI_STREAM,
                    )

            final_translator = self._final_translation_client()
            if final_translator is None:
                log_stage("llm_refine", chunk_id=chunk_id, status="skipped", detail="final model is off")
                return
            managed_status = self._final_status_managed()
            final_label = self._final_translation_label()
            if not managed_status:
                self._on_provider_status("active", final_label)
            translated = final_translator.translate(
                text, use_context=False, remember_context=False,
                context_text=context.context_text, deadline=deadline,
                previous_preview=context.previous_preview or None,
                live_hint=context.live_hint,
                on_update=emit_before_deadline,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            if not managed_status:
                self._on_provider_status("ok", final_label, elapsed_ms)
            if (
                translated
                and self.running
                and (paused is None or not paused.is_set())
                and time.monotonic() < deadline
            ):
                self._emit_ranked_translation(chunk_id, text, translated, "final", 3)
                log_stage("llm_refine", chunk_id=chunk_id, elapsed_ms=elapsed_ms, detail=translated)
        except TimeoutError as exc:
            if not self._final_status_managed():
                self._on_provider_status(
                    "warning", self._final_translation_label(), detail="timeout"
                )
            print(f"[LLM Refinement {chunk_id}] Deadline exceeded: {exc}")
            log_stage("llm_refine", chunk_id=chunk_id, status="timeout", detail=str(exc))
        except Exception as exc:
            if not self._final_status_managed():
                self._on_provider_status(
                    "error", self._final_translation_label(), detail=type(exc).__name__
                )
            # Keep the Apple draft visible on all remote API failures.
            print(f"[LLM Refinement {chunk_id}] Failed: {exc}")
            log_stage("llm_refine", chunk_id=chunk_id, status="error", detail=str(exc))

    def _run_translation(self, text, chunk_id, context, deadline):
        """Run translation in background and emit result"""
        draft = None
        try:
            if not self.running or self._paused.is_set() or time.monotonic() >= deadline:
                return
            if self._fast_translation_ready():
                try:
                    draft = self.fast_translator.translate(text)
                    if not self._paused.is_set():
                        self._emit_subtitle(
                            chunk_id,
                            text,
                            draft,
                            "final",
                            SubtitleStage.APPLE_FINAL,
                        )
                except Exception as exc:
                    print(f"[Apple Final Translation {chunk_id}] Failed: {exc}")

            if not should_request_remote(text):
                log_stage(
                    "remote_refine", chunk_id=chunk_id, status="skipped",
                    words=len(text.split()), detail="short or low-value final",
                )
                return

            def emit_before_deadline(partial):
                if self.running and not self._paused.is_set() and time.monotonic() < deadline:
                    self._emit_subtitle(
                        chunk_id,
                        text,
                        partial,
                        "final",
                        SubtitleStage.AI_STREAM,
                    )

            final_translator = self._final_translation_client()
            if final_translator is None:
                return
            context = self._normalise_translation_context(context)
            translated = final_translator.translate(
                text, use_context=False, remember_context=False,
                context_text=context.context_text, deadline=deadline,
                previous_preview=context.previous_preview or None,
                live_hint=context.live_hint,
                on_update=emit_before_deadline,
            )
            print(f"[Final {chunk_id}] Translated: {translated}")
            if self.running and not self._paused.is_set() and time.monotonic() < deadline:
                self._emit_subtitle(
                    chunk_id,
                    text,
                    translated,
                    "final",
                    SubtitleStage.AI_FINAL,
                )
        except TimeoutError as e:
            print(f"[Translation {chunk_id}] Deadline exceeded: {e}")
            log_stage("translation", chunk_id=chunk_id, status="timeout", detail=str(e))
        except Exception as e:
            print(f"[Translation {chunk_id}] Failed: {e}")
            log_stage("translation", chunk_id=chunk_id, status="error", detail=str(e))
            if not draft and not self._paused.is_set():
                self._emit_subtitle(
                    chunk_id,
                    text,
                    "[Translation Failed]",
                    "final",
                    SubtitleStage.ERROR,
                )

    @staticmethod
    def _normalise_translation_context(context, previous_preview=""):
        """Accept legacy context strings while all new paths use snapshots."""
        if hasattr(context, "context_text"):
            return context
        return ContextPolicy().final(
            (str(context or ""),) if context else (),
            previous_preview=previous_preview,
            history_limit=1,
        )
    
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
        translator = self._final_translation_client()
        if translator is None:
            return (text, "")
        translated_text = translator.translate(text)
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
    window = create_overlay(OverlaySpec(
        display_duration=config.display_duration,
        window_width=config.window_width,
        window_height=config.window_height,
        display_mode=config.display_mode,
        system_audio=config.device_index == "system",
    ))
    window.show()
    
    # Logic
    _pipeline = Pipeline()
    
    # Connect signals
    if hasattr(window, "update_event"):
        from subtitle_display_scheduler import (
            SubtitleDisplayScheduler,
            interval_for_pacing,
        )
        window._subtitle_display_scheduler = SubtitleDisplayScheduler(
            window.update_event,
            interval_ms=interval_for_pacing(config.subtitle_update_pacing),
            parent=window,
            presentation_policy=config.subtitle_presentation_policy,
        )
        _pipeline.signals.subtitle_event.connect(
            window._subtitle_display_scheduler.submit
        )
    else:
        _pipeline.signals.update_text.connect(window.update_text)
    
    # Start pipeline
    _pipeline.start()
    
    return window, _pipeline

def main():
    global _pipeline, _app
    from runtime_log import begin_runtime_session
    begin_runtime_session(reset=True, enabled=config.diagnostics_enabled)
    
    # Set up signal handler for Ctrl-C
    signal.signal(signal.SIGINT, signal_handler)
    
    _app = QApplication.instance()
    if not _app:
        _app = QApplication(sys.argv)
    from app_identity import apply_app_identity
    apply_app_identity(_app)
    
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
