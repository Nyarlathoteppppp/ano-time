"""Translator session lifecycle, separate from Dashboard presentation code."""

import time

from runtime_log import log_stage
from session_settings import SessionSettingsSnapshot, describe_session
from overlay_factory import OverlaySpec, create_overlay
from subtitle_display_scheduler import SubtitleDisplayScheduler
from translation_usage import session_usage_meter


class SessionController:
    def __init__(self, view, startup_worker_factory, transcript_recorder_factory=None):
        self.view = view
        self.startup_worker_factory = startup_worker_factory
        if transcript_recorder_factory is None:
            from session_transcript_recorder import SessionTranscriptRecorder

            transcript_recorder_factory = SessionTranscriptRecorder
        self.transcript_recorder_factory = transcript_recorder_factory

    def start(self):
        view = self.view
        if view._session_state in ("starting", "running"):
            if view.overlay_window:
                view.overlay_window.show()
            return

        view._session_generation += 1
        generation = view._session_generation
        view._session_state = "starting"
        topic_field = getattr(view, "current_course_topic", None)
        session_topic = (
            topic_field.text().strip()
            if topic_field is not None and hasattr(topic_field, "text")
            else ""
        )
        try:
            saved = view.save_config(show_status=False)
            if saved is False:
                raise RuntimeError("settings were not saved")
        except Exception as exc:
            view._session_state = "idle"
            view.status_label.setText(f"Unable to save settings: {exc}")
            view.status_label.setStyleSheet("font-size: 18px; color: #f38ba8;")
            view.start_btn.setEnabled(True)
            view.start_btn.setText("▶ Launch Translator")
            log_stage("session_start", status="error", detail=f"settings: {exc}")
            return
        # A Launch defines one billing session. Reset before Pipeline creation
        # so its optional warm-up request is included in the same totals.
        from config import config
        session_settings = SessionSettingsSnapshot.from_config(config).with_overrides(
            current_course_topic=session_topic
        )
        view._active_session_settings = session_settings
        set_description = getattr(view, "set_active_session_description", None)
        if set_description:
            set_description(describe_session(session_settings), state="starting")
        session_usage_meter.set_enabled(session_settings.usage_tracking_enabled)
        session_usage_meter.reset()
        view.status_label.setText("Initializing Pipeline... (This may take a moment)")
        view.status_label.setStyleSheet("font-size: 18px; color: #fab387;")
        view.start_btn.setEnabled(False)
        view.start_btn.setText("Loading...")

        try:
            worker = self.startup_worker_factory(generation, session_settings)
        except TypeError:
            # External test/launcher factories predating session snapshots may
            # still take only a generation. The shipped worker receives both.
            worker = self.startup_worker_factory(generation)
        view._startup_workers[generation] = worker
        worker.ready.connect(view.on_pipeline_ready)
        worker.finished.connect(
            lambda generation=generation: view._startup_workers.pop(generation, None)
        )
        worker.start()

    def pipeline_ready(self, generation, pipeline):
        view = self.view
        if generation != view._session_generation or view._session_state != "starting":
            if pipeline:
                pipeline.stop()
            return

        if not pipeline:
            view._session_state = "idle"
            view.status_label.setText("Initialization Failed Check Console")
            view.start_btn.setEnabled(True)
            view.start_btn.setText("▶ Launch Translator")
            return

        view.pipeline = pipeline
        set_description = getattr(view, "set_active_session_description", None)
        if set_description:
            active_settings = getattr(pipeline, "settings", None)
            if active_settings is None:
                active_settings = getattr(view, "_active_session_settings", None)
            if active_settings is None:
                from config import config
                active_settings = config
            description = getattr(pipeline, "session_description", None)
            set_description(
                description or describe_session(active_settings),
                state="running",
            )
        settings = getattr(pipeline, "settings", None)
        if settings is None:
            from config import config
            settings = config
        actual_audio = type(view.pipeline.audio).__name__
        if actual_audio == "SystemAudioCapture":
            view.audio_summary.setText("System Audio · ScreenCaptureKit active")
            view.audio_summary.setStyleSheet("color: #a6e3a1; font-weight: 600;")
        else:
            view.audio_summary.setText(f"Microphone · {view.device_combo.currentText()}")
            view.audio_summary.setStyleSheet("color: #f9e2af; font-weight: 600;")

        if view.overlay_window:
            view.overlay_window.close()
            view.overlay_window = None
        view.overlay_window = create_overlay(OverlaySpec(
            display_duration=settings.display_duration,
            window_width=settings.window_width,
            window_height=settings.window_height,
            display_mode=settings.display_mode,
            system_audio=actual_audio == "SystemAudioCapture",
        ))
        view.overlay_window.show()

        if hasattr(view.overlay_window, "update_event"):
            view.subtitle_display_scheduler = SubtitleDisplayScheduler(
                view.overlay_window.update_event,
                parent=view.overlay_window,
            )
            view.pipeline.signals.subtitle_event.connect(
                view.subtitle_display_scheduler.submit
            )
        else:
            view.subtitle_display_scheduler = None
            view.pipeline.signals.update_text.connect(
                view.overlay_window.update_text
            )
        previous_recorder = getattr(view, "transcript_recorder", None)
        if previous_recorder:
            previous_recorder.stop()
        view.transcript_recorder = None
        recording_status = getattr(view, "set_transcript_recording_status", None)
        if settings.auto_save_transcripts:
            try:
                view.transcript_recorder = self.transcript_recorder_factory()
                view.pipeline.signals.subtitle_event.connect(
                    view.transcript_recorder.update_event
                )
                if recording_status:
                    recording_status(
                        "recording", str(view.transcript_recorder.path)
                    )
                log_stage(
                    "transcript_recording",
                    status="ok",
                    detail=str(view.transcript_recorder.path),
                )
            except Exception as exc:
                # Recording is useful but must never block live captions.
                view.transcript_recorder = None
                log_stage("transcript_recording", status="error", detail=str(exc))
                if recording_status:
                    recording_status("error", detail=str(exc))
        elif recording_status:
            recording_status("off")
        view.pipeline.signals.pipeline_error.connect(view.on_pipeline_error)
        view.pipeline.signals.runtime_status.connect(self.handle_runtime_status)
        if hasattr(view.overlay_window, "update_runtime_status"):
            view.pipeline.signals.runtime_status.connect(
                view.overlay_window.update_runtime_status
            )
        if hasattr(view.overlay_window, "stop_requested"):
            view.overlay_window.stop_requested.connect(view.on_stop)
        if hasattr(view.overlay_window, "pause_requested"):
            view.overlay_window.pause_requested.connect(
                lambda paused: view._set_pipeline_paused(paused, update_overlay=False)
            )

        view.pipeline.start()
        view._session_state = "running"
        view.status_label.setText("Running...")
        view.status_label.setStyleSheet("font-size: 18px; color: #a6e3a1;")
        view.start_btn.hide()
        if hasattr(view, "pause_btn"):
            view.pause_btn.setText("⏸ Pause Translator")
            view.pause_btn.show()
        view.stop_btn.show()
        # Keep the control center available from the Dock, but explicitly
        # remove its AppKit vibrancy child from composition while minimized.
        view.showMinimized()
        sync_glass = getattr(view, "_sync_native_glass", None)
        if sync_glass:
            sync_glass()

    def pipeline_error(self, message):
        view = self.view
        self.stop()
        concise = " ".join(str(message).split())[:180]
        view.status_label.setText(f"Stopped — {concise}")
        view.status_label.setStyleSheet("font-size: 16px; color: #f38ba8;")
        view.showNormal()

    def set_paused(self, paused, update_overlay=True):
        view = self.view
        if not view.pipeline:
            return
        started = time.perf_counter()
        view.pipeline.set_paused(paused)
        # A resumed session waits for fresh speech before restarting the
        # projection clock, so an unattended paused/resumed app stays idle.
        session_usage_meter.set_active(False)
        if update_overlay and view.overlay_window and hasattr(
            view.overlay_window, "set_paused"
        ):
            view.overlay_window.set_paused(paused)
        if paused:
            view.status_label.setText("Paused · ⌃S to resume")
            view.status_label.setStyleSheet("font-size: 16px; color: #f9e2af;")
            if hasattr(view, "pause_btn"):
                view.pause_btn.setText("▶ Resume Translator")
        else:
            view.status_label.setText("Running · ⌃S to pause")
            view.status_label.setStyleSheet("font-size: 16px; color: #a6e3a1;")
            if hasattr(view, "pause_btn"):
                view.pause_btn.setText("⏸ Pause Translator")
        log_stage(
            "session_pause" if paused else "session_resume",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def handle_runtime_status(self, stage, status, detail):
        """Update presentation and start cost projection on real speech."""
        # Starting the process is not billable classroom time. Begin the
        # hourly projection only after Apple produces its first ASR partial.
        # Raw RMS/audio activity is deliberately insufficient. This also
        # excludes optional model warm-up from the projection while retaining
        # it in the exact session total.
        pipeline = getattr(self.view, "pipeline", None)
        session_running = getattr(self.view, "_session_state", "running") == "running"
        pipeline_paused = bool(
            pipeline is not None and getattr(pipeline, "is_paused", False)
        )
        if (
            stage == "ASR"
            and status == "active"
            and session_running
            and pipeline is not None
            and not pipeline_paused
        ):
            session_usage_meter.set_active(True)
        self.view.update_runtime_status(stage, status, detail)

    def stop(self):
        view = self.view
        started = time.perf_counter()
        view._session_generation += 1
        view._session_state = "idle"
        view._active_session_settings = None
        set_description = getattr(view, "set_active_session_description", None)
        if set_description:
            set_description("尚未启动", state="idle")
        session_usage_meter.set_active(False)
        if view.overlay_window:
            view.overlay_window.close()
            view.overlay_window = None
        if view.pipeline:
            view.pipeline.stop()
            view.pipeline = None
        transcript_recorder = getattr(view, "transcript_recorder", None)
        if transcript_recorder:
            transcript_path = str(getattr(transcript_recorder, "path", ""))
            transcript_recorder.stop()
            view.transcript_recorder = None
            recording_status = getattr(
                view, "set_transcript_recording_status", None
            )
            if recording_status:
                recording_status("saved", transcript_path)
        view.status_label.setText("Stopped")
        view.stop_btn.hide()
        if hasattr(view, "pause_btn"):
            view.pause_btn.hide()
        view.start_btn.show()
        view.start_btn.setEnabled(True)
        view.start_btn.setText("▶ Launch Translator")
        view.showNormal()
        log_stage("session_stop", elapsed_ms=(time.perf_counter() - started) * 1000)
