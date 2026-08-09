"""macOS permission navigation and system-audio probe orchestration."""

import subprocess


class PermissionController:
    def __init__(self, view, audio_test_worker_factory):
        self.view = view
        self.audio_test_worker_factory = audio_test_worker_factory

    @staticmethod
    def open_accessibility_settings():
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ])

    @staticmethod
    def open_system_audio_settings():
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        ])

    def test_system_audio(self):
        view = self.view
        if view._session_state in ("starting", "running"):
            view.audio_test_status.setText(
                "Stop the translator before running the independent audio test."
            )
            return
        view.test_system_audio_btn.setEnabled(False)
        view.test_system_audio_btn.setText("Testing…")
        view.audio_test_status.setText(
            "Listening for system audio for about two seconds. Play a video now."
        )
        view.audio_test_worker = self.audio_test_worker_factory(view.sample_rate.value())
        view.audio_test_worker.result.connect(self.on_system_audio_test_result)
        view.audio_test_worker.start()

    def on_system_audio_test_result(self, success, message, peak):
        view = self.view
        view.test_system_audio_btn.setEnabled(True)
        view.test_system_audio_btn.setText("Test Permission & Audio")
        if success and peak > 0.0001:
            color = "#a6e3a1"
            text = f"Permission works. System audio detected (peak {peak:.4f})."
        elif success:
            color = "#f9e2af"
            text = (
                "Permission works, but the captured audio was silent. "
                "Play a video with audible sound and test again."
            )
        else:
            color = "#f38ba8"
            text = message
        view.audio_test_status.setText(text)
        view.audio_test_status.setStyleSheet(
            f"color: {color}; background: rgba(255,255,255,14); "
            "padding: 10px; border-radius: 8px;"
        )
