"""Global shortcut lifecycle and settings, isolated from Dashboard layout code."""

import os

from ui.qt import QtWidgets


QCheckBox = QtWidgets.QCheckBox
QDialog = QtWidgets.QDialog
QHBoxLayout = QtWidgets.QHBoxLayout
QLabel = QtWidgets.QLabel
QPushButton = QtWidgets.QPushButton
QVBoxLayout = QtWidgets.QVBoxLayout


class ShortcutController:
    def __init__(self, view, stylesheet):
        self.view = view
        self.stylesheet = stylesheet
        from global_shortcut import MacCarbonHotkeyShortcut

        self.shortcut = MacCarbonHotkeyShortcut(
            enabled=view.shortcut_enabled,
            parent=view,
        )
        self.shortcut.activated.connect(self.activated)

    def start(self):
        hotkey_agent_plist = os.path.expanduser(
            "~/Library/LaunchAgents/com.nyarlathotep.realtime-ton.hotkey.plist"
        )
        if os.path.exists(hotkey_agent_plist):
            print("[Shortcut] External hotkey agent owns Control + S", flush=True)
        else:
            self.shortcut.start()
        self.update_button()

    def stop(self):
        self.shortcut.stop()

    def update_button(self):
        if not hasattr(self.view, "shortcut_btn"):
            return
        state = "On" if self.view.shortcut_enabled else "Off"
        self.view.shortcut_btn.setText(f"⌃S · {state}")

    def open_settings(self):
        dialog = QDialog(self.view)
        dialog.setWindowTitle("Global Shortcut Settings")
        dialog.setMinimumWidth(440)
        dialog.setStyleSheet(self.stylesheet)
        layout = QVBoxLayout(dialog)

        title = QLabel("⌃S（Control + S）")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #89b4fa;")
        layout.addWidget(title)

        enabled = QCheckBox("Enable global shortcut（启用全局快捷键）")
        enabled.setChecked(self.view.shortcut_enabled)
        layout.addWidget(enabled)

        explanation = QLabel(
            "Idle: launch directly in Physical MacBook Notch mode.\n"
            "Running: pause. Paused: resume.\n"
            "Uses the native macOS global hotkey API and does not require "
            "Accessibility or Input Monitoring permission."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet(
            "color: #a6adc8; background: rgba(255,255,255,14); "
            "padding: 10px; border-radius: 8px;"
        )
        layout.addWidget(explanation)

        actions = QHBoxLayout()
        cancel = QPushButton("Cancel")
        save = QPushButton("Save")
        cancel.clicked.connect(dialog.reject)
        save.clicked.connect(dialog.accept)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.view.shortcut_enabled = enabled.isChecked()
        self.shortcut.set_enabled(self.view.shortcut_enabled)
        self.update_button()
        self.view.save_config(show_status=False)
        self.view.status_label.setText("Shortcut settings saved · Control + S")
        self.view.status_label.setStyleSheet("font-size: 16px; color: #a6e3a1;")

    def activated(self):
        view = self.view
        if not view.shortcut_enabled:
            return
        if view._session_state == "idle":
            notch_index = view.display_mode.findData("notch")
            if notch_index >= 0:
                view.display_mode.setCurrentIndex(notch_index)
            view.status_label.setText("⌃S · launching notch translator…")
            view.status_label.setStyleSheet("font-size: 16px; color: #89b4fa;")
            view.on_start()
            return
        if view._session_state == "starting":
            view.status_label.setText("Translator is already starting…")
            return
        if view.pipeline:
            view._set_pipeline_paused(not view.pipeline.is_paused)
