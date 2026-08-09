"""Translator session lifecycle, separate from Dashboard presentation code."""

import time

from runtime_log import log_stage


class SessionController:
    def __init__(self, view, startup_worker_factory):
        self.view = view
        self.startup_worker_factory = startup_worker_factory

    def start(self):
        view = self.view
        if view._session_state in ("starting", "running"):
            if view.overlay_window:
                view.overlay_window.show()
            return

        view._session_generation += 1
        generation = view._session_generation
        view._session_state = "starting"
        view.save_config(show_status=False)
        view.status_label.setText("Initializing Pipeline... (This may take a moment)")
        view.status_label.setStyleSheet("font-size: 18px; color: #fab387;")
        view.start_btn.setEnabled(False)
        view.start_btn.setText("Loading...")

        worker = self.startup_worker_factory(generation)
        view._startup_workers[generation] = worker
        worker.ready.connect(view.on_pipeline_ready)
        worker.finished.connect(
            lambda generation=generation: view._startup_workers.pop(generation, None)
        )
        worker.start()

    def pipeline_ready(self, generation, pipeline):
        from config import config

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
        if view.display_mode.currentData() == "notch":
            from native_notch_overlay import NativeNotchOverlay as OverlayClass
        else:
            from overlay_window import OverlayWindow as OverlayClass
        overlay_kwargs = dict(
            display_duration=config.display_duration,
            window_width=config.window_width,
            window_height=config.window_height,
            display_mode=view.display_mode.currentData(),
        )
        if view.display_mode.currentData() != "notch":
            overlay_kwargs["video_overlay"] = actual_audio == "SystemAudioCapture"
        view.overlay_window = OverlayClass(**overlay_kwargs)
        view.overlay_window.show()

        view.pipeline.signals.update_text.connect(view.overlay_window.update_text)
        view.pipeline.signals.pipeline_error.connect(view.on_pipeline_error)
        view.pipeline.signals.runtime_status.connect(view.update_runtime_status)
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

    def stop(self):
        view = self.view
        started = time.perf_counter()
        view._session_generation += 1
        view._session_state = "idle"
        if view.overlay_window:
            view.overlay_window.close()
            view.overlay_window = None
        if view.pipeline:
            view.pipeline.stop()
            view.pipeline = None
        view.status_label.setText("Stopped")
        view.stop_btn.hide()
        if hasattr(view, "pause_btn"):
            view.pause_btn.hide()
        view.start_btn.show()
        view.start_btn.setEnabled(True)
        view.start_btn.setText("▶ Launch Translator")
        view.showNormal()
        log_stage("session_stop", elapsed_ms=(time.perf_counter() - started) * 1000)
