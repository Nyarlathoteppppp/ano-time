from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QComboBox, QLineEdit, 
                             QTabWidget, QSpinBox, QDoubleSpinBox, QGridLayout,
                             QScrollArea, QSizePolicy, QSpacerItem, QFormLayout, QApplication,
                             QMessageBox, QTextEdit, QDialog, QLayout)
from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtGui import QFont, QIcon, QColor
import sys
import sounddevice as sd
from config import config
from runtime_version import current_version

try:
    from ctypes import c_void_p
    from AppKit import (
        NSBackingStoreBuffered, NSColor, NSPanel,
        NSViewHeightSizable, NSViewWidthSizable,
        NSVisualEffectBlendingModeBehindWindow,
        NSVisualEffectMaterialHUDWindow, NSVisualEffectStateActive,
        NSVisualEffectView, NSWindowBelow, NSWindowStyleMaskBorderless,
    )
    import objc
    HAS_NATIVE_GLASS = True
except ImportError:
    HAS_NATIVE_GLASS = False

# Modern QSS Styles
STYLESHEET = """
QWidget {
    background: transparent;
    color: #cdd6f4;
    font-family: 'Helvetica Neue', Arial, sans-serif;
}
QWidget#DashboardRoot {
    background-color: rgba(15, 20, 30, 72);
}
QTabWidget::pane {
    border: 1px solid rgba(255, 255, 255, 35);
    background: rgba(20, 24, 36, 55);
    border-radius: 12px;
}
QTabBar::tab {
    background: rgba(255, 255, 255, 18);
    color: #a6adc8;
    padding: 10px 20px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: rgba(137, 180, 250, 210);
    color: #10131c;
    font-weight: bold;
}
QLabel {
    font-size: 14px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: rgba(255, 255, 255, 20);
    border: 1px solid rgba(255, 255, 255, 42);
    border-radius: 7px;
    padding: 6px;
    color: #cdd6f4;
    selection-background-color: #585b70;
}
QComboBox QAbstractItemView {
    background-color: rgba(28, 32, 44, 245);
    border: 1px solid rgba(255, 255, 255, 45);
    color: #cdd6f4;
    selection-background-color: rgba(137, 180, 250, 190);
    selection-color: #10131c;
}
QComboBox QAbstractItemView::item {
    min-height: 30px;
    padding: 4px 10px;
}
QPushButton {
    background-color: rgba(137, 180, 250, 205);
    color: #10131c;
    border: 1px solid rgba(255, 255, 255, 30);
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: rgba(180, 190, 254, 235);
}
QPushButton#StopButton {
    background-color: #f38ba8;
}
QPushButton#StopButton:hover {
    background-color: #eba0ac;
}
QGroupBox {
    border: 1px solid rgba(255, 255, 255, 38);
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    color: #fab387;
}
"""


class ReadableComboBox(QComboBox):
    """Combo box whose popup fits its longest item without clipping."""

    def addItem(self, text, userData=None):
        super().addItem(text, userData)
        self.setItemData(
            self.count() - 1, str(text), Qt.ItemDataRole.ToolTipRole
        )

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)

    def showPopup(self):
        metrics = self.fontMetrics()
        content_width = max(
            [metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())]
            or [self.width()]
        ) + 56
        screen = self.screen() or QApplication.primaryScreen()
        screen_limit = int(screen.availableGeometry().width() * 0.72) if screen else 760
        self.view().setMinimumWidth(
            max(self.width(), min(content_width, screen_limit, 760))
        )
        super().showPopup()

class Dashboard(QWidget):
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    def closeEvent(self, event):
        """Ensure total program quit when dashboard is closed"""
        self.status_label.setText("Stopping...")
        self.on_stop()
        audio_test = getattr(self, "audio_test_worker", None)
        if audio_test and audio_test.isRunning():
            audio_test.wait(2500)
        shortcut = getattr(self, "global_shortcut", None)
        if shortcut:
            shortcut.stop()
        if self._native_blur_window is not None:
            self._native_blur_window.close()
            self._native_blur_window = None
            self._native_blur_view = None
        # Force application exit
        QApplication.quit()
        event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self._install_native_glass()
        # Qt's QNSWindow can be attached one event-loop turn after showEvent.
        QTimer.singleShot(0, self._install_native_glass)
        QTimer.singleShot(200, self._install_native_glass)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._sync_native_glass()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_native_glass()

    def _native_window(self):
        if not HAS_NATIVE_GLASS:
            return None
        try:
            ns_view = objc.objc_object(c_void_p=c_void_p(int(self.winId())))
            return ns_view.window()
        except Exception as exc:
            print(f"[Dashboard] Could not resolve native window: {exc}")
            return None

    def _install_native_glass(self):
        if not HAS_NATIVE_GLASS or self._native_blur_window is not None:
            return
        ns_window = self._native_window()
        if ns_window is None:
            return
        ns_window.setOpaque_(False)
        ns_window.setBackgroundColor_(NSColor.clearColor())
        ns_window.setTitlebarAppearsTransparent_(True)

        blur_window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ns_window.frame(), NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered, False,
        )
        blur_window.setOpaque_(False)
        blur_window.setBackgroundColor_(NSColor.clearColor())
        blur_window.setHasShadow_(False)
        blur_window.setIgnoresMouseEvents_(True)
        blur_window.setHidesOnDeactivate_(False)

        effect = NSVisualEffectView.alloc().initWithFrame_(
            blur_window.contentView().bounds()
        )
        effect.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(NSVisualEffectStateActive)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(16.0)
        effect.layer().setMasksToBounds_(True)
        blur_window.contentView().addSubview_(effect)
        ns_window.addChildWindow_ordered_(blur_window, NSWindowBelow)
        self._native_blur_window = blur_window
        self._native_blur_view = effect
        self._sync_native_glass()
        print("[Dashboard] Native macOS glass installed", flush=True)

    def _sync_native_glass(self):
        blur_window = getattr(self, "_native_blur_window", None)
        if blur_window is None:
            return
        ns_window = self._native_window()
        if ns_window is None:
            return
        blur_window.setFrame_display_(ns_window.frame(), True)
        blur_window.orderFrontRegardless()
        ns_window.orderFrontRegardless()

    def __init__(self):
        super().__init__()
        self._native_blur_window = None
        self._native_blur_view = None
        self.setObjectName("DashboardRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._session_generation = 0
        self._session_state = "idle"
        self._startup_workers = {}
        self.pipeline = None
        self.overlay_window = None
        self.shortcut_enabled = config.shortcut_enabled
        self.shortcut_interval = config.shortcut_interval
        self.setWindowTitle("Real-Time Translator - Control Center")
        self.setMinimumSize(760, 540)
        self.setStyleSheet(STYLESHEET)
        
        # Main Layout
        self.layout = QVBoxLayout()
        self.layout.setSpacing(20)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.setLayout(self.layout)
        
        # Header
        header = QLabel(f"🎙️ Real-Time Translator  ·  {current_version()}")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #89b4fa;")
        self.layout.addWidget(header)
        
        # Tabs
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        
        self.init_home_tab()
        self.init_audio_tab()
        self.init_device_manager_tab()
        self.init_transcription_tab()
        self.init_translation_tab()
        self.update_home_summary()

        from global_shortcut import MacDoubleOptionShortcut
        self.global_shortcut = MacDoubleOptionShortcut(
            enabled=self.shortcut_enabled,
            interval_seconds=self.shortcut_interval,
            parent=self,
        )
        self.global_shortcut.activated.connect(self.on_global_shortcut)
        self.global_shortcut.start()
        self._update_shortcut_button()
        
        # Footer Actions
        footer = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_config)
        self.save_btn.setStyleSheet("""
            background-color: #a6e3a1; color: #1e1e2e;
        """)
        footer.addStretch()
        footer.addWidget(self.save_btn)
        self.layout.addLayout(footer)

    def init_home_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 18px; color: #a6e3a1;")
        layout.addWidget(self.status_label)

        summary = QFrame()
        summary.setObjectName("ClassroomSummary")
        summary.setStyleSheet("""
            QFrame#ClassroomSummary {
                background-color: rgba(255, 255, 255, 14);
                border: 1px solid rgba(255, 255, 255, 32);
                border-radius: 10px;
            }
            QFrame#ClassroomSummary QLabel { background: transparent; }
        """)
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(16, 12, 16, 12)
        summary_layout.addWidget(QLabel("Audio（音频来源）"), 0, 0)
        summary_layout.addWidget(QLabel("ASR（语音识别）"), 1, 0)
        summary_layout.addWidget(QLabel("Translation（翻译模型）"), 2, 0)
        self.audio_summary = QLabel()
        self.asr_summary = QLabel()
        self.translation_summary = QLabel()
        for label in (self.audio_summary, self.asr_summary, self.translation_summary):
            label.setStyleSheet("color: #a6e3a1; font-weight: 600;")
        summary_layout.addWidget(self.audio_summary, 0, 1)
        summary_layout.addWidget(self.asr_summary, 1, 1)
        summary_layout.addWidget(self.translation_summary, 2, 1)
        layout.addWidget(summary)

        runtime = QFrame()
        runtime.setObjectName("RuntimeStatus")
        runtime.setMinimumHeight(164)
        runtime.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        runtime.setStyleSheet("""
            QFrame#RuntimeStatus {
                background-color: rgba(255, 255, 255, 10);
                border: 1px solid rgba(255, 255, 255, 25);
                border-radius: 9px;
            }
            QFrame#RuntimeStatus QLabel { background: transparent; }
        """)
        runtime_layout = QGridLayout(runtime)
        runtime_layout.setContentsMargins(14, 10, 14, 10)
        self.runtime_labels = {}
        for row, (key, title) in enumerate((
            ("ASR", "ASR"),
            ("Draft", "Apple Draft（快速草稿）"),
            ("Remote", "Remote Model（远程模型）"),
            ("Network", "Network（网络）"),
        )):
            runtime_layout.setRowMinimumHeight(row, 30)
            title_label = QLabel(title)
            title_label.setMinimumHeight(26)
            runtime_layout.addWidget(title_label, row, 0)
            value = QLabel("Waiting")
            value.setMinimumHeight(26)
            value.setStyleSheet("color: #6c7086; font-weight: 600;")
            runtime_layout.addWidget(value, row, 1)
            self.runtime_labels[key] = value
        layout.addWidget(runtime)

        display_row = QHBoxLayout()
        display_row.addWidget(QLabel("Subtitle Mode（字幕显示模式）:"))
        self.display_mode = ReadableComboBox()
        self.display_mode.addItem("Resizable Glass", "glass")
        self.display_mode.addItem("Physical MacBook Notch", "notch")
        mode_index = self.display_mode.findData(config.display_mode)
        self.display_mode.setCurrentIndex(max(0, mode_index))
        display_row.addWidget(self.display_mode)
        layout.addLayout(display_row)
        
        btn_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("▶ Launch Translator")
        self.start_btn.setFixedSize(200, 60)
        self.start_btn.setStyleSheet("font-size: 16px; background-color: #89b4fa; border-radius: 10px;")
        self.start_btn.clicked.connect(self.on_start)
        
        self.stop_btn = QPushButton("⏹ Stop Translator")
        self.stop_btn.setFixedSize(200, 60)
        self.stop_btn.setStyleSheet("font-size: 16px; background-color: #f38ba8; border-radius: 10px;")
        self.stop_btn.clicked.connect(self.on_stop)
        self.stop_btn.hide()

        self.log_btn = QPushButton("📄 Open Runtime Log")
        self.log_btn.setFixedSize(200, 38)
        self.log_btn.clicked.connect(self.open_runtime_log)

        self.shortcut_btn = QPushButton("⌥⌥ Shortcut Settings")
        self.shortcut_btn.setFixedSize(240, 38)
        self.shortcut_btn.clicked.connect(self.open_shortcut_settings)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)
        layout.addWidget(self.log_btn)
        layout.addWidget(self.shortcut_btn)
        
        info = QLabel("The translator will open as an overlay window.\nYou can minimize this dashboard.")
        info.setStyleSheet("color: #6c7086; font-style: italic;")
        layout.addWidget(info)
        
        tab.setLayout(layout)
        scroll = QScrollArea()
        scroll.setObjectName("HomeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setWidget(tab)
        self.home_scroll = scroll
        self.tabs.addTab(scroll, "🏠 Home")

    def open_runtime_log(self):
        import subprocess
        from runtime_log import LOG_PATH
        subprocess.run(["open", LOG_PATH], check=False)

    def _update_shortcut_button(self):
        if not hasattr(self, "shortcut_btn"):
            return
        state = "On" if self.shortcut_enabled else "Off"
        interval_ms = int(round(self.shortcut_interval * 1000))
        self.shortcut_btn.setText(
            f"⌥⌥ Double Option · {state} · {interval_ms} ms"
        )

    def open_shortcut_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Global Shortcut Settings")
        dialog.setMinimumWidth(440)
        dialog.setStyleSheet(STYLESHEET)
        layout = QVBoxLayout(dialog)

        title = QLabel("⌥⌥ Double Option（双击 Option）")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #89b4fa;")
        layout.addWidget(title)

        enabled = QCheckBox("Enable global shortcut（启用全局快捷键）")
        enabled.setChecked(self.shortcut_enabled)
        layout.addWidget(enabled)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Double-tap interval（双击间隔）:"))
        interval = QSpinBox()
        interval.setRange(200, 600)
        interval.setSingleStep(20)
        interval.setSuffix(" ms")
        interval.setValue(int(round(self.shortcut_interval * 1000)))
        interval_row.addWidget(interval)
        layout.addLayout(interval_row)

        explanation = QLabel(
            "Idle: launch directly in Physical MacBook Notch mode.\n"
            "Running: pause. Paused: resume.\n"
            "Option combined with any other key is ignored. If it does not react "
            "outside the app, allow Realtime Translator under macOS Accessibility."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet(
            "color: #a6adc8; background: rgba(255,255,255,14); "
            "padding: 10px; border-radius: 8px;"
        )
        layout.addWidget(explanation)

        permission_btn = QPushButton("Open Accessibility Settings（打开辅助功能权限）")
        permission_btn.clicked.connect(self.open_accessibility_settings)
        layout.addWidget(permission_btn)

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
        self.shortcut_enabled = enabled.isChecked()
        self.shortcut_interval = interval.value() / 1000.0
        self.global_shortcut.set_enabled(self.shortcut_enabled)
        self.global_shortcut.set_interval(self.shortcut_interval)
        self._update_shortcut_button()
        self.save_config(show_status=False)
        self.status_label.setText("Shortcut settings saved · Double Option")
        self.status_label.setStyleSheet("font-size: 16px; color: #a6e3a1;")

    def open_accessibility_settings(self):
        import subprocess
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ])

    def on_global_shortcut(self):
        if not self.shortcut_enabled:
            return
        if self._session_state == "idle":
            notch_index = self.display_mode.findData("notch")
            if notch_index >= 0:
                self.display_mode.setCurrentIndex(notch_index)
            self.status_label.setText("Double Option · launching notch translator…")
            self.status_label.setStyleSheet("font-size: 16px; color: #89b4fa;")
            self.on_start()
            return
        if self._session_state == "starting":
            self.status_label.setText("Translator is already starting…")
            return
        if self.pipeline:
            self._set_pipeline_paused(not self.pipeline.is_paused)

    def _set_pipeline_paused(self, paused, update_overlay=True):
        if not self.pipeline:
            return
        self.pipeline.set_paused(paused)
        if update_overlay and self.overlay_window and hasattr(
            self.overlay_window, "set_paused"
        ):
            self.overlay_window.set_paused(paused)
        if paused:
            self.status_label.setText("Paused · Double Option to resume")
            self.status_label.setStyleSheet("font-size: 16px; color: #f9e2af;")
        else:
            self.status_label.setText("Running · Double Option to pause")
            self.status_label.setStyleSheet("font-size: 16px; color: #a6e3a1;")

    def update_runtime_status(self, stage, status, detail):
        label = self.runtime_labels.get(stage)
        if not label:
            return
        colors = {
            "ok": "#a6e3a1",
            "active": "#89b4fa",
            "warning": "#f9e2af",
            "error": "#f38ba8",
        }
        label.setText(detail)
        label.setStyleSheet(
            f"color: {colors.get(status, '#cdd6f4')}; font-weight: 600;"
        )

    def update_home_summary(self, *_):
        if not hasattr(self, "audio_summary"):
            return
        source_data = self.device_combo.currentData() if hasattr(self, "device_combo") else config.device_index
        if source_data == "system":
            source = "System Audio · videos/apps"
            source_color = "#a6e3a1"
        elif source_data in ("auto", None):
            source = "Default microphone"
            source_color = "#f9e2af"
        else:
            source = self.device_combo.currentText() if hasattr(self, "device_combo") else f"Device {source_data}"
            source_color = "#f9e2af"
        self.audio_summary.setText(source)
        self.audio_summary.setStyleSheet(f"color: {source_color}; font-weight: 600;")

        backend = self.asr_backend.currentText() if hasattr(self, "asr_backend") else config.asr_backend
        self.asr_summary.setText(
            "Apple on-device (live)" if backend == "apple" else backend
        )
        model = self.model.currentText() if hasattr(self, "model") else config.model
        self.translation_summary.setText(model)

    def use_system_audio(self):
        index = self.device_combo.findData("system")
        if index >= 0:
            self.device_combo.setCurrentIndex(index)
        self.save_config(show_status=False)
        self.update_home_summary()
        if self._session_state == "running":
            message = "System Audio selected. Stop and Launch again to apply it."
        else:
            message = "System Audio selected and saved. Launch Translator when ready."
        self.audio_test_status.setText(message)
        self.audio_test_status.setStyleSheet(
            "color: #a6e3a1; background: rgba(255,255,255,14); padding: 10px; border-radius: 8px;"
        )

    def open_system_audio_settings(self):
        import subprocess
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        ])

    def test_system_audio(self):
        if self._session_state in ("starting", "running"):
            self.audio_test_status.setText(
                "Stop the translator before running the independent audio test."
            )
            return
        self.test_system_audio_btn.setEnabled(False)
        self.test_system_audio_btn.setText("Testing…")
        self.audio_test_status.setText(
            "Listening for system audio for about two seconds. Play a video now."
        )
        self.audio_test_worker = SystemAudioTestWorker(self.sample_rate.value())
        self.audio_test_worker.result.connect(self.on_system_audio_test_result)
        self.audio_test_worker.start()

    def on_system_audio_test_result(self, success, message, peak):
        self.test_system_audio_btn.setEnabled(True)
        self.test_system_audio_btn.setText("Test Permission & Audio")
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
        self.audio_test_status.setText(text)
        self.audio_test_status.setStyleSheet(
            f"color: {color}; background: rgba(255,255,255,14); padding: 10px; border-radius: 8px;"
        )

    def init_audio_tab(self):
        tab = QWidget()
        layout = QGridLayout() # Use Grid for organized form
        layout.setSpacing(15)
        
        # Device Selection
        layout.addWidget(QLabel("Input Device（音频来源）:"), 0, 0)
        self.device_combo = ReadableComboBox()
        self.populate_devices()
        self.device_combo.currentIndexChanged.connect(self.update_home_summary)
        layout.addWidget(self.device_combo, 0, 1)
        
        # Refresh Button
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedWidth(40)
        refresh_btn.clicked.connect(self.populate_devices)
        layout.addWidget(refresh_btn, 0, 2)
        
        # Sample Rate
        layout.addWidget(QLabel("Sample Rate（采样率）:"), 1, 0)
        self.sample_rate = QSpinBox()
        self.sample_rate.setRange(8000, 48000)
        self.sample_rate.setValue(config.sample_rate)
        layout.addWidget(self.sample_rate, 1, 1)

        # Silence Threshold
        layout.addWidget(QLabel("Silence Threshold（静音判定阈值）:"), 2, 0)
        self.silence_thresh = QDoubleSpinBox()
        self.silence_thresh.setRange(0.001, 1.0)
        self.silence_thresh.setSingleStep(0.001)
        self.silence_thresh.setDecimals(3)
        self.silence_thresh.setValue(config.silence_threshold)
        layout.addWidget(self.silence_thresh, 2, 1)
        
        layout.addWidget(QLabel("Silence Duration（持续静音多久才断句，秒）:"), 3, 0)
        self.silence_dur = QDoubleSpinBox()
        self.silence_dur.setValue(config.silence_duration)
        layout.addWidget(self.silence_dur, 3, 1)

        layout.addWidget(QLabel("Live Refresh Interval（临时字幕刷新间隔，秒）:"), 4, 0)
        self.update_interval = QDoubleSpinBox()
        self.update_interval.setRange(0.2, 2.0)
        self.update_interval.setSingleStep(0.1)
        self.update_interval.setDecimals(1)
        self.update_interval.setValue(config.update_interval)
        self.update_interval.setToolTip(
            "Lower values update partial subtitles faster. 0.5 s is recommended for class."
        )
        layout.addWidget(self.update_interval, 4, 1)

        action_row = QHBoxLayout()
        self.use_system_audio_btn = QPushButton("Use System Audio")
        self.use_system_audio_btn.setToolTip(
            "Select native ScreenCaptureKit audio from videos and applications"
        )
        self.use_system_audio_btn.clicked.connect(self.use_system_audio)
        action_row.addWidget(self.use_system_audio_btn)

        self.test_system_audio_btn = QPushButton("Test Permission & Audio")
        self.test_system_audio_btn.clicked.connect(self.test_system_audio)
        action_row.addWidget(self.test_system_audio_btn)

        self.open_audio_permission_btn = QPushButton("Open Permission Settings")
        self.open_audio_permission_btn.clicked.connect(self.open_system_audio_settings)
        action_row.addWidget(self.open_audio_permission_btn)
        layout.addLayout(action_row, 5, 0, 1, 3)

        self.audio_test_status = QLabel(
            "System Audio uses macOS ScreenCaptureKit; BlackHole is not required."
        )
        self.audio_test_status.setWordWrap(True)
        self.audio_test_status.setStyleSheet(
            "color: #a6adc8; background: rgba(255,255,255,14); padding: 10px; border-radius: 8px;"
        )
        layout.addWidget(self.audio_test_status, 6, 0, 1, 3)

        layout.setRowStretch(7, 1) # Push to top
        
        tab.setLayout(layout)
        self.tabs.addTab(tab, "🎤 Audio")

    def init_device_manager_tab(self):
        """Audio Device Manager - Create/Manage Multi-Output Devices"""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        # Header
        header = QLabel("Legacy BlackHole Routing")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #fab387;")
        layout.addWidget(header)
        
        info = QLabel(
            "Optional legacy/custom routing. Normal macOS system-audio capture uses "
            "ScreenCaptureKit on the Audio tab and does not need BlackHole."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #6c7086; font-size: 12px; font-style: italic;")
        layout.addWidget(info)
        
        # Available Devices List
        devices_label = QLabel("Available Output Devices:")
        layout.addWidget(devices_label)
        
        self.output_devices_list = ReadableComboBox()
        self.output_devices_list.setMinimumHeight(30)
        layout.addWidget(self.output_devices_list)
        
        # Virtual Device List
        virtual_label = QLabel("Virtual/BlackHole Devices:")
        layout.addWidget(virtual_label)
        
        self.virtual_devices_list = ReadableComboBox()
        self.virtual_devices_list.setMinimumHeight(30)
        layout.addWidget(self.virtual_devices_list)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.refresh_devices_btn = QPushButton("🔄 Refresh Devices")
        self.refresh_devices_btn.clicked.connect(self.refresh_audio_devices)
        btn_layout.addWidget(self.refresh_devices_btn)
        
        self.create_multi_output_btn = QPushButton("➕ Create Multi-Output Device")
        self.create_multi_output_btn.setStyleSheet("""
            background-color: #a6e3a1; color: #1e1e2e; font-weight: bold;
        """)
        self.create_multi_output_btn.clicked.connect(self.create_multi_output_device)
        btn_layout.addWidget(self.create_multi_output_btn)
        
        layout.addLayout(btn_layout)
        
        # Set as Default Button
        self.set_default_btn = QPushButton("🔊 Set Selected as Default Output")
        self.set_default_btn.clicked.connect(self.set_default_output_device)
        layout.addWidget(self.set_default_btn)
        
        # Status
        self.device_status = QLabel("Ready")
        self.device_status.setStyleSheet("color: #a6e3a1; font-style: italic; padding: 10px;")
        layout.addWidget(self.device_status)
        
        # Help text
        help_text = QLabel(
            "<b>How to use:</b><br>"
            "1. Select your speakers from 'Available Output Devices'<br>"
            "2. Select BlackHole from 'Virtual Devices'<br>"
            "3. Click 'Create Multi-Output Device'<br>"
            "   • Audio MIDI Setup will open with instructions<br>"
            "   • Follow the step-by-step guide in the terminal/console<br>"
            "4. The new device lets you hear audio AND capture it!<br>"
            "<br><i>Note: Accessibility permissions may be required for automation.<br>"
            "Without permissions, you'll see manual instructions (very easy!).</i>"
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("background-color: rgba(255,255,255,14); padding: 10px; border-radius: 8px; font-size: 12px;")
        layout.addWidget(help_text)
        
        layout.addStretch()
        
        tab.setLayout(layout)
        self.tabs.addTab(tab, "🔧 Legacy BlackHole")
        
        # Initial population
        self.refresh_audio_devices()

    def refresh_audio_devices(self):
        """Refresh the list of audio devices"""
        try:
            import platform
            if platform.system() != "Darwin":
                self.device_status.setText("⚠️ Device Manager only available on macOS")
                self.device_status.setStyleSheet("color: #fab387;")
                return
            
            from audio_device_manager import AudioDeviceManager
            manager = AudioDeviceManager()
            
            # Get output devices
            output_devices = manager.get_output_devices()
            self.output_devices_list.clear()
            for device in output_devices:
                self.output_devices_list.addItem(f"{device['name']}", device['id'])
            
            # Get virtual/BlackHole devices
            virtual_devices = manager.get_virtual_devices()
            self.virtual_devices_list.clear()
            if not virtual_devices:
                self.virtual_devices_list.addItem("No BlackHole device found - Please install it")
                self.device_status.setText("⚠️ BlackHole not found. Install: brew install blackhole-2ch")
                self.device_status.setStyleSheet("color: #fab387;")
            else:
                for device in virtual_devices:
                    self.virtual_devices_list.addItem(f"{device['name']}", device['id'])
                self.device_status.setText("✅ Devices loaded successfully")
                self.device_status.setStyleSheet("color: #a6e3a1;")
                
        except ImportError:
            self.device_status.setText("⚠️ Audio device management requires PyObjC (pip install pyobjc-framework-CoreAudio)")
            self.device_status.setStyleSheet("color: #f38ba8;")
        except Exception as e:
            self.device_status.setText(f"❌ Error: {str(e)}")
            self.device_status.setStyleSheet("color: #f38ba8;")
    
    def create_multi_output_device(self):
        """Create a multi-output device combining speakers + BlackHole"""
        try:
            from audio_device_manager import AudioDeviceManager
            manager = AudioDeviceManager()
            
            output_device_id = self.output_devices_list.currentData()
            virtual_device_id = self.virtual_devices_list.currentData()
            
            if not output_device_id or not virtual_device_id:
                self.device_status.setText("⚠️ Please select both devices")
                self.device_status.setStyleSheet("color: #fab387;")
                return
            
            # Show instruction dialog
            self._show_multi_output_instructions()
            
            # Call the audio device manager to open Audio MIDI Setup
            device_name = f"Translator Multi-Output"
            success = manager.create_multi_output_device(
                device_name,
                [output_device_id, virtual_device_id],
                silent=True  # Suppress console output, show GUI dialog instead
            )
            
            if success:
                self.device_status.setText(f"✅ Audio MIDI Setup opened - Follow the instructions!")
                self.device_status.setStyleSheet("color: #a6e3a1;")
                # Refresh after user has time to create the device
                QTimer = __import__('PyQt6.QtCore', fromlist=['QTimer']).QTimer
                QTimer.singleShot(3000, self.refresh_audio_devices)
            else:
                self.device_status.setText("❌ Failed to open Audio MIDI Setup")
                self.device_status.setStyleSheet("color: #f38ba8;")
                
        except Exception as e:
            self.device_status.setText(f"❌ Error: {str(e)}")
            self.device_status.setStyleSheet("color: #f38ba8;")
    
    def _show_multi_output_instructions(self):
        """Show a dialog with step-by-step instructions"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🎵 Create Multi-Output Device - Instructions")
        dialog.setMinimumSize(600, 500)
        dialog.setStyleSheet(STYLESHEET)
        
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("📋 Step-by-Step Guide")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #89b4fa; padding: 10px;")
        layout.addWidget(title)
        
        # Instructions text
        instructions = QTextEdit()
        instructions.setReadOnly(True)
        instructions.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 8px;
                padding: 15px;
                font-size: 13px;
                line-height: 1.6;
            }
        """)
        
        output_device = self.output_devices_list.currentText()
        virtual_device = self.virtual_devices_list.currentText()
        
        instructions_html = f"""
        <div style='font-family: Arial, sans-serif;'>
        <h3 style='color: #fab387;'>✨ Audio MIDI Setup is opening...</h3>
        
        <p style='color: #a6adc8;'><b>Follow these simple steps:</b></p>
        
        <div style='background: #313244; padding: 12px; border-radius: 6px; margin: 10px 0;'>
        <p style='color: #89b4fa; font-weight: bold;'>👉 Step 1: Find the Plus Button</p>
        <p>In the Audio MIDI Setup window, look at the <b>bottom-left corner</b>.<br>
        Click the <span style='background: #45475a; padding: 2px 8px; border-radius: 3px;'>[+]</span> button.</p>
        </div>
        
        <div style='background: #313244; padding: 12px; border-radius: 6px; margin: 10px 0;'>
        <p style='color: #89b4fa; font-weight: bold;'>👉 Step 2: Create Multi-Output</p>
        <p>From the menu that appears, select:<br>
        <span style='color: #a6e3a1; font-weight: bold;'>“Create Multi-Output Device”</span></p>
        </div>
        
        <div style='background: #313244; padding: 12px; border-radius: 6px; margin: 10px 0;'>
        <p style='color: #89b4fa; font-weight: bold;'>👉 Step 3: Select Devices</p>
        <p>Check the boxes for these devices:<br>
        ✅ <span style='color: #f9e2af;'>{output_device}</span> (your speakers)<br>
        ✅ <span style='color: #f9e2af;'>{virtual_device}</span> (for capturing)</p>
        </div>
        
        <div style='background: #313244; padding: 12px; border-radius: 6px; margin: 10px 0;'>
        <p style='color: #89b4fa; font-weight: bold;'>👉 Step 4: Configure Drift Correction</p>
        <p><b style='color: #f38ba8;'>IMPORTANT:</b> Uncheck <b>“Drift Correction”</b> for <span style='color: #f9e2af;'>{output_device}</span><br>
        (This allows you to hear the audio through your speakers)</p>
        </div>
        
        <div style='background: #313244; padding: 12px; border-radius: 6px; margin: 10px 0;'>
        <p style='color: #89b4fa; font-weight: bold;'>👉 Step 5: Set as Default Output</p>
        <p>Go to <b>System Settings → Sound</b><br>
        Set the new <span style='color: #a6e3a1;'>Multi-Output Device</span> as your output device.</p>
        </div>
        
        <hr style='border: 1px solid #45475a; margin: 15px 0;'>
        
        <p style='color: #6c7086; font-style: italic;'>
        💡 <b>Tip:</b> You only need to do this once! The device will persist across reboots.<br>
        After setup, you'll hear audio normally while the translator captures it in real-time.
        </p>
        </div>
        """
        
        instructions.setHtml(instructions_html)
        layout.addWidget(instructions)
        
        # Close button
        close_btn = QPushButton("✅ Got it!")
        close_btn.setFixedHeight(40)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #a6e3a1;
                color: #1e1e2e;
                font-weight: bold;
                font-size: 14px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #b4e4b4;
            }
        """)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.setLayout(layout)
        dialog.exec()
    
    def set_default_output_device(self):
        """Set the selected device as system default output"""
        try:
            from audio_device_manager import AudioDeviceManager
            manager = AudioDeviceManager()
            
            device_id = self.output_devices_list.currentData()
            if not device_id:
                self.device_status.setText("⚠️ Please select a device")
                self.device_status.setStyleSheet("color: #fab387;")
                return
            
            device_name = self.output_devices_list.currentText()
            success = manager.set_default_output_device(device_id)
            
            if success:
                self.device_status.setText(f"✅ Set '{device_name}' as default output")
                self.device_status.setStyleSheet("color: #a6e3a1;")
            else:
                self.device_status.setText("❌ Failed to set default device")
                self.device_status.setStyleSheet("color: #f38ba8;")
                
        except Exception as e:
            self.device_status.setText(f"❌ Error: {str(e)}")
            self.device_status.setStyleSheet("color: #f38ba8;")

    def refresh_model_list(self):
        """Fetch available models from the API and populate the model dropdown"""
        try:
            from openai import OpenAI
            import httpx
            
            api_key = self.api_key.text() or "dummy-key-for-local"
            base_url = self.base_url.text() or None
            
            # Update button state
            self.refresh_models_btn.setEnabled(False)
            self.refresh_models_btn.setText("...")
            
            # Create client with SSL verification disabled
            http_client = httpx.Client(verify=False)
            client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
            
            # Fetch models
            models_response = client.models.list()
            model_ids = [model.id for model in models_response.data]
            
            # Update combo box
            current_model = self.model.currentText()
            self.model.clear()
            
            if model_ids:
                self.model.addItems(sorted(model_ids))
                # Try to restore previous selection
                index = self.model.findText(current_model)
                if index >= 0:
                    self.model.setCurrentIndex(index)
                    
                # Show success in status label if we're on the home tab
                if hasattr(self, 'status_label'):
                    self.status_label.setText(f"✅ Loaded {len(model_ids)} models")
                    self.status_label.setStyleSheet("font-size: 18px; color: #a6e3a1;")
            else:
                self.model.addItem(current_model)
                if hasattr(self, 'status_label'):
                    self.status_label.setText("⚠️ No models found")
                    self.status_label.setStyleSheet("font-size: 18px; color: #fab387;")
            
        except Exception as e:
            # Restore original model on error
            if not self.model.currentText():
                self.model.addItem(config.model)
            
            error_msg = str(e)
            if hasattr(self, 'status_label'):
                self.status_label.setText(f"❌ Failed to fetch models: {error_msg[:50]}")
                self.status_label.setStyleSheet("font-size: 18px; color: #f38ba8;")
            print(f"[Dashboard] Model refresh error: {error_msg}")
        
        finally:
            # Restore button state
            self.refresh_models_btn.setEnabled(True)
            self.refresh_models_btn.setText("🔄")

    def init_transcription_tab(self):
        tab = QWidget()
        layout = QFormLayout()
        layout.setVerticalSpacing(14)
        self.transcription_layout = layout
        
        # ASR Backend Selection
        self.asr_backend = ReadableComboBox()
        self.asr_backend.addItems(["apple", "whisper", "mlx", "funasr"])
        self.asr_backend.setCurrentText(config.asr_backend)
        self.asr_backend.setToolTip(
            "whisper: CPU/CUDA (faster-whisper)\n"
            "mlx: Apple Silicon GPU (mlx-whisper)\n"
            "funasr: Alibaba ASR (excellent for Chinese)"
        )
        self.asr_backend.currentTextChanged.connect(self._on_backend_changed)
        self.asr_backend.currentTextChanged.connect(self.update_home_summary)
        layout.addRow("ASR Backend（语音识别引擎）:", self.asr_backend)

        self.backend_hint = QLabel()
        self.backend_hint.setWordWrap(True)
        self.backend_hint.setStyleSheet(
            "color: #a6e3a1; padding: 8px 10px; "
            "background: rgba(255, 255, 255, 12); border-radius: 7px;"
        )
        layout.addRow("", self.backend_hint)
        
        # Whisper Model
        self.whisper_model = ReadableComboBox()
        self.whisper_model.addItems(["tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large-v3", "turbo"])
        self.whisper_model.setCurrentText(config.whisper_model)
        layout.addRow("Whisper Model（Whisper 模型大小）:", self.whisper_model)
        
        # FunASR Model
        self.funasr_model = ReadableComboBox()
        self.funasr_model.setEditable(True)
        self.funasr_model.addItems([
            "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            "iic/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online",
            "iic/speech_UniASR_asr_2pass-vi-16k-common-vocab1001-pytorch-online",
            "iic/speech_UniASR_asr_2pass-en-16k-common-vocab1080-tensorflow1-online",
            "iic/SenseVoiceSmall",
            "FunAudioLLM/SenseVoiceSmall",
            "FunAudioLLM/Fun-ASR-Nano-2512",
            "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        ])
        self.funasr_model.setCurrentText(config.funasr_model)
        self.funasr_model.setToolTip(
            "Chinese (Offline): iic/speech_paraformer-large...\n"
            "Chinese (Streaming): iic/speech_paraformer_asr_nat...online\n"
            "English (Streaming): iic/speech_UniASR_asr_2pass-en...\n"
            "Multi-language: iic/SenseVoiceSmall\n"
            "Latest 31-lang model: FunAudioLLM/Fun-ASR-Nano-2512"
        )
        layout.addRow("FunASR Model（FunASR 模型）:", self.funasr_model)
        
        self.device_type = ReadableComboBox()
        self.device_type.addItems(["cpu", "cuda", "mps", "auto"])
        self.device_type.setCurrentText(config.whisper_device)
        self.device_type.currentTextChanged.connect(self._on_device_changed)
        layout.addRow("Compute Device（计算设备）:", self.device_type)
        
        self.compute_type = ReadableComboBox()
        self.compute_type.addItems(["int8", "float16", "float32"])
        self.compute_type.setCurrentText(config.whisper_compute_type)
        self.compute_type.currentTextChanged.connect(self._on_quantization_changed)
        layout.addRow("Quantization（推理精度与内存占用）:", self.compute_type)
        
        # Source Language Configuration
        self.source_language = ReadableComboBox()
        self.source_language.setEditable(True)
        self.source_language.addItems(["auto", "en", "zh", "vi", "ja", "ko", "es", "fr", "de", "ru", "ar", "pt", "it"])
        source_lang = config.source_language if config.source_language else "auto"
        self.source_language.setCurrentText(source_lang)
        layout.addRow("Source Language（原文语言）:", self.source_language)
        
        # Update UI based on initial backend
        self._on_backend_changed(config.asr_backend)
        
        tab.setLayout(layout)
        self.tabs.addTab(tab, "📝 Transcription")
    
    def _on_backend_changed(self, backend):
        """Show only settings consumed by the selected ASR backend."""
        is_whisper_or_mlx = backend in ["whisper", "mlx"]
        is_funasr = backend == "funasr"

        self._set_transcription_row_visible(self.whisper_model, is_whisper_or_mlx)
        self._set_transcription_row_visible(self.funasr_model, is_funasr)
        self._set_transcription_row_visible(
            self.device_type, backend in ["whisper", "funasr"]
        )
        self._set_transcription_row_visible(self.compute_type, backend == "whisper")

        hints = {
            "apple": "Apple 原生实时识别：只使用原文语言，其他模型参数已隐藏。",
            "mlx": "MLX Whisper：使用所选 Whisper 模型，并自动调用 Apple Silicon Metal。",
            "whisper": "Faster-Whisper：模型、计算设备和推理精度均会参与运行。",
            "funasr": "FunASR：使用所选模型和计算设备；MPS 会自动采用 float32。",
        }
        self.backend_hint.setText(hints.get(backend, ""))
        
        # Check MPS + FunASR quantization compatibility
        if is_funasr:
            self._check_funasr_mps_compatibility()

    def _set_transcription_row_visible(self, field, visible):
        field.setVisible(visible)
        label = self.transcription_layout.labelForField(field)
        if label:
            label.setVisible(visible)
    
    def _check_funasr_mps_compatibility(self):
        """Check if MPS device is used with FunASR and enforce float32"""
        current_device = self.device_type.currentText()
        current_quantization = self.compute_type.currentText()
        
        if current_device == "mps" and current_quantization != "float32":
            self._show_mps_float32_warning()
            # Auto-switch to float32
            float32_index = self.compute_type.findText("float32")
            if float32_index >= 0:
                self.compute_type.setCurrentIndex(float32_index)
    
    def _show_mps_float32_warning(self):
        """Show warning about MPS requiring float32 with FunASR"""
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Quantization Compatibility")
        msg.setText("MPS device requires float32 quantization with FunASR")
        msg.setInformativeText(
            "Apple's MPS (Metal Performance Shaders) does not support float64 operations.\n\n"
            "When using FunASR with MPS device, quantization must be set to 'float32'.\n\n"
            "The quantization has been automatically switched to float32."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    
    def _on_device_changed(self, device):
        """Check device compatibility when user changes device selection"""
        # Check MPS + FunASR quantization compatibility
        if self.asr_backend.currentText() == "funasr":
            self._check_funasr_mps_compatibility()
    
    def _on_quantization_changed(self, quantization):
        """Check quantization compatibility when user changes quantization"""
        # Check MPS + FunASR quantization compatibility
        if self.asr_backend.currentText() == "funasr":
            self._check_funasr_mps_compatibility()

    def init_translation_tab(self):
        tab = QWidget()
        layout = QFormLayout()

        self.provider = ReadableComboBox()
        self.provider.addItems([
            "Fast Free Pool → Qwen-MT",
            "Alibaba Cloud Qwen-MT",
            "DeepSeek Official",
            "SiliconFlow",
            "Custom",
        ])
        current_base = (config.api_base_url or "").lower()
        if "api.deepseek.com" in current_base:
            self.provider.setCurrentText("DeepSeek Official")
        elif "siliconflow" in current_base:
            self.provider.setCurrentText("SiliconFlow")
        elif "maas.aliyuncs.com" in current_base or "dashscope" in current_base:
            self.provider.setCurrentText("Alibaba Cloud Qwen-MT")
        else:
            self.provider.setCurrentText("Custom")
        if config.translation_provider == "Fast Free Pool → Qwen-MT":
            self.provider.setCurrentText("Fast Free Pool → Qwen-MT")
        self._current_provider = self.provider.currentText()
        self.provider_keys = {
            "DeepSeek Official": config.deepseek_api_key or config.api_key,
            "SiliconFlow": config.siliconflow_api_key,
            "Alibaba Cloud Qwen-MT": config.qwen_mt_api_key,
            "Fast Free Pool → Qwen-MT": "",
            "Custom": config.api_key,
        }
        self.provider_urls = {
            "DeepSeek Official": "https://api.deepseek.com",
            "SiliconFlow": "https://api.siliconflow.cn/v1",
            "Alibaba Cloud Qwen-MT": config.qwen_mt_base_url,
            "Custom": config.api_base_url or "",
        }
        self.provider.currentTextChanged.connect(self._on_translation_provider_changed)
        layout.addRow("Provider（翻译服务商）:", self.provider)
        
        self.api_key = QLineEdit(config.api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-...")
        layout.addRow("API Key（主翻译服务密钥）:", self.api_key)

        self.groq_api_key = QLineEdit(config.groq_api_key)
        self.groq_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.groq_api_key.setPlaceholderText("gsk_...")
        layout.addRow("Groq Key（快速过渡翻译密钥）:", self.groq_api_key)

        self.gemini_api_key = QLineEdit(config.gemini_api_key)
        self.gemini_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_api_key.setPlaceholderText("Google AI Studio key")
        layout.addRow("Gemini Key（Gemini 免费池密钥）:", self.gemini_api_key)

        self.cloudflare_account_id = QLineEdit(config.cloudflare_account_id)
        self.cloudflare_account_id.setPlaceholderText("Cloudflare account ID")
        layout.addRow("Cloudflare Account（账户 ID）:", self.cloudflare_account_id)

        self.cloudflare_api_token = QLineEdit(config.cloudflare_api_token)
        self.cloudflare_api_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloudflare_api_token.setPlaceholderText("Cloudflare API token")
        layout.addRow("Cloudflare Token（Workers AI 访问令牌）:", self.cloudflare_api_token)
        
        self.base_url = QLineEdit(config.api_base_url or "")
        self.base_url.setPlaceholderText("https://api.openai.com/v1")
        layout.addRow("Base URL（API 接口地址）:", self.base_url)
        
        # Model selection with refresh button
        model_layout = QHBoxLayout()
        self.model = ReadableComboBox()
        self.model.setEditable(True)
        self.model.addItem(config.model)
        self.model.currentTextChanged.connect(self.update_home_summary)
        model_layout.addWidget(self.model)
        
        self.refresh_models_btn = QPushButton("🔄")
        self.refresh_models_btn.setFixedWidth(40)
        self.refresh_models_btn.setToolTip("Refresh model list from API")
        self.refresh_models_btn.clicked.connect(self.refresh_model_list)
        model_layout.addWidget(self.refresh_models_btn)
        
        layout.addRow("Model（翻译模型）:", model_layout)
        
        self.target_lang = ReadableComboBox()
        self.target_lang.addItems(["Chinese", "English", "Japanese", "French", "Spanish", "German", "Korean"])
        self.target_lang.setEditable(True)
        self.target_lang.setCurrentText(config.target_lang)
        layout.addRow("Target Language（目标语言）:", self.target_lang)

        self.translation_domain = QLineEdit(config.translation_domain)
        self.translation_domain.setPlaceholderText(
            "Postgraduate computer science coursework with mathematics terminology"
        )
        self.translation_domain.setToolTip(
            "Domain context sent to the translation model to preserve technical terminology"
        )
        layout.addRow("Course Domain（课程专业背景）:", self.translation_domain)

        self.fast_translation_backend = ReadableComboBox()
        self.fast_translation_backend.addItems(["apple", "off"])
        self.fast_translation_backend.setCurrentText(config.fast_translation_backend)
        self.fast_translation_backend.setToolTip(
            "apple: show an immediate on-device draft, then replace it with the LLM-refined translation"
        )
        layout.addRow("Instant Draft（即时草稿翻译）:", self.fast_translation_backend)

        self._on_translation_provider_changed(self.provider.currentText())
        
        tab.setLayout(layout)
        self.tabs.addTab(tab, "🈵 Translation")

    def _on_translation_provider_changed(self, provider):
        if hasattr(self, "api_key"):
            self.provider_keys[self._current_provider] = self.api_key.text()
            self.provider_urls[self._current_provider] = self.base_url.text()
            self.api_key.setText(self.provider_keys.get(provider, ""))
        self._current_provider = provider
        hybrid = provider == "Fast Free Pool → Qwen-MT"
        if hasattr(self, "base_url"):
            self.api_key.setEnabled(not hybrid)
            self.base_url.setEnabled(not hybrid)
            self.model.setEnabled(not hybrid)
            self.refresh_models_btn.setEnabled(not hybrid)
        if hybrid:
            self.base_url.setText("Automatic quota-aware rotation")
            self.model.setCurrentText("Apple → Groq bridge → Gemini/GLM → Qwen-MT")
        elif provider == "DeepSeek Official":
            self.base_url.setText("https://api.deepseek.com")
            self.model.setCurrentText("deepseek-v4-flash")
        elif provider == "SiliconFlow":
            self.base_url.setText("https://api.siliconflow.cn/v1")
            if self.model.currentText().startswith("deepseek-v4-"):
                self.model.setCurrentText("deepseek-ai/DeepSeek-V4-Flash")
        elif provider == "Alibaba Cloud Qwen-MT":
            self.base_url.setText(self.provider_urls.get(provider, ""))
            self.base_url.setPlaceholderText(
                "https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
            )
            self.model.setCurrentText("qwen-mt-flash")
        else:
            self.base_url.setText(self.provider_urls.get(provider, self.base_url.text()))

    def populate_devices(self):
        self.device_combo.clear()
        self.device_combo.addItem("Auto (Default)", "auto")
        self.device_combo.addItem(
            "System Audio (ScreenCaptureKit — videos/apps)", "system"
        )
        
        try:
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if d['max_input_channels'] > 0:
                    name = f"[{i}] {d['name']}"
                    self.device_combo.addItem(name, i) # Store index as data
            
            # Select current
            if config.device_index is not None:
                index = self.device_combo.findData(config.device_index)
                if index >= 0:
                    self.device_combo.setCurrentIndex(index)
        except Exception as e:
            self.device_combo.addItem(f"Error: {e}")

    def save_config(self, checked=False, show_status=True):
        import configparser
        import os
        from keychain_store import SECRET_FIELDS, store as keychain
        
        # Update config object logic would go here, 
        # For now, we write directly to config.ini similarly to settings_window.py
        
        cp = configparser.ConfigParser()
        config_path = os.path.join(os.path.dirname(__file__), "config.ini")
        cp.read(config_path)
        
        if not cp.has_section("audio"): cp.add_section("audio")
        if not cp.has_section("api"): cp.add_section("api")
        if not cp.has_section("translation"): cp.add_section("translation")
        if not cp.has_section("transcription"): cp.add_section("transcription")
        if not cp.has_section("providers"): cp.add_section("providers")
        if not cp.has_section("display"): cp.add_section("display")
        if not cp.has_section("shortcut"): cp.add_section("shortcut")
        
        # Audio
        idx = self.device_combo.currentData()
        cp.set("audio", "device_index", str(idx) if idx is not None else "auto")
        cp.set("audio", "sample_rate", str(self.sample_rate.value()))
        cp.set("audio", "silence_threshold", str(self.silence_thresh.value()))
        cp.set("audio", "silence_duration", str(self.silence_dur.value()))
        cp.set("audio", "update_interval", str(self.update_interval.value()))
        
        # Transcription
        cp.set("transcription", "backend", self.asr_backend.currentText())
        cp.set("transcription", "whisper_model", self.whisper_model.currentText())
        cp.set("transcription", "funasr_model", self.funasr_model.currentText())
        cp.set("transcription", "device", self.device_type.currentText())
        cp.set("transcription", "compute_type", self.compute_type.currentText())
        cp.set("transcription", "source_language", self.source_language.currentText())
        
        # Translation
        if self.provider.currentText() != "Fast Free Pool → Qwen-MT":
            cp.set(
                "api", "api_key",
                keychain.store_for_config(
                    SECRET_FIELDS[("api", "api_key")], self.api_key.text()
                ),
            )
            cp.set("api", "base_url", self.base_url.text())
            cp.set("translation", "model", self.model.currentText())
        cp.set("translation", "target_lang", self.target_lang.currentText())
        cp.set("translation", "domain", self.translation_domain.text())
        cp.set("translation", "fast_backend", self.fast_translation_backend.currentText())
        cp.set("translation", "provider", self.provider.currentText())
        self.provider_keys[self.provider.currentText()] = self.api_key.text()
        self.provider_urls[self.provider.currentText()] = self.base_url.text()
        cp.set("providers", "deepseek_api_key", keychain.store_for_config(
            SECRET_FIELDS[("providers", "deepseek_api_key")],
            self.provider_keys.get("DeepSeek Official", ""),
        ))
        cp.set("providers", "siliconflow_api_key", keychain.store_for_config(
            SECRET_FIELDS[("providers", "siliconflow_api_key")],
            self.provider_keys.get("SiliconFlow", ""),
        ))
        cp.set("providers", "qwen_mt_api_key", keychain.store_for_config(
            SECRET_FIELDS[("providers", "qwen_mt_api_key")],
            self.provider_keys.get("Alibaba Cloud Qwen-MT", ""),
        ))
        cp.set("providers", "qwen_mt_base_url", self.provider_urls.get("Alibaba Cloud Qwen-MT", ""))
        cp.set("providers", "groq_api_key", keychain.store_for_config(
            SECRET_FIELDS[("providers", "groq_api_key")], self.groq_api_key.text()
        ))
        cp.set("providers", "gemini_api_key", keychain.store_for_config(
            SECRET_FIELDS[("providers", "gemini_api_key")], self.gemini_api_key.text()
        ))
        cp.set("providers", "cloudflare_account_id", self.cloudflare_account_id.text())
        cp.set("providers", "cloudflare_api_token", keychain.store_for_config(
            SECRET_FIELDS[("providers", "cloudflare_api_token")],
            self.cloudflare_api_token.text(),
        ))
        cp.set("display", "mode", self.display_mode.currentData())
        cp.set("shortcut", "enabled", "true" if self.shortcut_enabled else "false")
        cp.set("shortcut", "double_tap_interval", str(self.shortcut_interval))
        
        with open(config_path, 'w') as f:
            cp.write(f)
        os.chmod(config_path, 0o600)

        config.reload()
        if show_status:
            suffix = " Applies on next launch." if getattr(self, "pipeline", None) else ""
            self.status_label.setText(f"Saved.{suffix}")

    def on_start(self):
        if self._session_state in ("starting", "running"):
            if self.overlay_window:
                self.overlay_window.show()
            return

        self._session_generation += 1
        generation = self._session_generation
        self._session_state = "starting"
        # Launch exactly what is visible in the Dashboard; no separate Save click required.
        self.save_config(show_status=False)
        # 1. Update UI to Loading State
        self.status_label.setText("Initializing Pipeline... (This may take a moment)")
        self.status_label.setStyleSheet("font-size: 18px; color: #fab387;") # Orange for loading
        self.start_btn.setEnabled(False)
        self.start_btn.setText("Loading...")
        
        # 2. Start Worker Thread
        worker = StartupWorker(generation)
        self._startup_workers[generation] = worker
        worker.ready.connect(self.on_pipeline_ready)
        worker.finished.connect(
            lambda generation=generation: self._startup_workers.pop(generation, None)
        )
        worker.start()

    def on_pipeline_ready(self, generation, pipeline):
        # Create Window on Main Thread
        from config import config

        # A Stop/new Launch invalidates every older startup. Dispose its native
        # helpers instead of allowing a late callback to create another window.
        if generation != self._session_generation or self._session_state != "starting":
            if pipeline:
                pipeline.stop()
            return

        if not pipeline:
            self._session_state = "idle"
            self.status_label.setText("Initialization Failed Check Console")
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶ Launch Translator")
            return

        self.pipeline = pipeline
        actual_audio = type(self.pipeline.audio).__name__
        if actual_audio == "SystemAudioCapture":
            self.audio_summary.setText("System Audio · ScreenCaptureKit active")
            self.audio_summary.setStyleSheet("color: #a6e3a1; font-weight: 600;")
        else:
            self.audio_summary.setText(
                f"Microphone · {self.device_combo.currentText()}"
            )
            self.audio_summary.setStyleSheet("color: #f9e2af; font-weight: 600;")
        if self.overlay_window:
            self.overlay_window.close()
            self.overlay_window = None
        if self.display_mode.currentData() == "notch":
            from native_notch_overlay import NativeNotchOverlay as OverlayClass
        else:
            from overlay_window import OverlayWindow as OverlayClass
        overlay_kwargs = dict(
            display_duration=config.display_duration,
            window_width=config.window_width,
            window_height=config.window_height,
            display_mode=self.display_mode.currentData(),
        )
        if self.display_mode.currentData() != "notch":
            overlay_kwargs["video_overlay"] = actual_audio == "SystemAudioCapture"
        self.overlay_window = OverlayClass(**overlay_kwargs)
        self.overlay_window.show()

        # Connect Signals
        self.pipeline.signals.update_text.connect(self.overlay_window.update_text)
        self.pipeline.signals.pipeline_error.connect(self.on_pipeline_error)
        self.pipeline.signals.runtime_status.connect(self.update_runtime_status)
        if hasattr(self.overlay_window, 'stop_requested'):
             self.overlay_window.stop_requested.connect(self.close)
        if hasattr(self.overlay_window, 'pause_requested'):
             self.overlay_window.pause_requested.connect(
                 lambda paused: self._set_pipeline_paused(paused, update_overlay=False)
             )

        # Start Pipeline Thread
        self.pipeline.start()
        self._session_state = "running"

        self.status_label.setText("Running...")
        self.status_label.setStyleSheet("font-size: 18px; color: #a6e3a1;")
        
        self.start_btn.hide()
        self.stop_btn.show()
        
        self.showMinimized()

    def on_pipeline_error(self, message):
        """Surface background capture/ASR failures instead of showing Running."""
        self.on_stop()
        concise = " ".join(str(message).split())[:180]
        self.status_label.setText(f"Stopped — {concise}")
        self.status_label.setStyleSheet("font-size: 16px; color: #f38ba8;")
        self.showNormal()

    def on_stop(self):
        self._session_generation += 1
        self._session_state = "idle"

        if self.overlay_window:
            self.overlay_window.close()
            self.overlay_window = None

        if self.pipeline:
            self.pipeline.stop()
            self.pipeline = None
            
        self.status_label.setText("Stopped")
        self.stop_btn.hide()
        self.start_btn.show()
        self.start_btn.setEnabled(True)
        self.start_btn.setText("▶ Launch Translator")
        self.showNormal()

class SystemAudioTestWorker(QThread):
    result = pyqtSignal(bool, str, float)

    def __init__(self, sample_rate):
        super().__init__()
        self.sample_rate = sample_rate

    def run(self):
        capture = None
        peak = 0.0
        success = False
        message = ""
        try:
            import numpy as np
            from system_audio_capture import SystemAudioCapture

            capture = SystemAudioCapture(
                sample_rate=self.sample_rate,
                streaming_step_size=0.2,
            )
            generator = capture.generator()
            for _ in range(10):
                chunk = next(generator)
                if len(chunk):
                    peak = max(peak, float(np.max(np.abs(chunk))))
            success = True
            message = "System audio permission is available."
        except Exception as exc:
            message = (
                "System Audio could not start. Open permission settings, allow the "
                f"translator/Python helper, then restart. Detail: {exc}"
            )
        finally:
            if capture:
                capture.stop()
        self.result.emit(success, message, peak)


class StartupWorker(QThread):
    ready = pyqtSignal(int, object)

    def __init__(self, generation):
        super().__init__()
        self.generation = generation

    def run(self):
        try:
            from main import Pipeline
            pipeline = Pipeline()
            self.ready.emit(self.generation, pipeline)
        except Exception as e:
            print(f"Startup Error: {e}")
            import traceback
            traceback.print_exc()
            self.ready.emit(self.generation, None)


INSTANCE_SERVER_NAME = "com.realtime-ton.dashboard"


def notify_existing_instance(command=b"activate"):
    """Send a command to the running Dashboard process."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_SERVER_NAME)
    if not socket.waitForConnected(250):
        return False
    socket.write(command)
    socket.waitForBytesWritten(250)
    socket.disconnectFromServer()
    return True


def start_instance_server(on_activate, on_quit):
    """Own the process-wide singleton socket, recovering stale socket files."""
    server = QLocalServer()
    if not server.listen(INSTANCE_SERVER_NAME):
        # A process may have won the singleton race after our initial probe.
        # Never unlink its live socket; only remove the path if connection fails.
        if notify_existing_instance():
            return None
        QLocalServer.removeServer(INSTANCE_SERVER_NAME)
        if not server.listen(INSTANCE_SERVER_NAME):
            return None

    def accept_connections():
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connection.waitForReadyRead(100)
            command = bytes(connection.readAll()).strip()
            if command == b"quit":
                on_quit()
            else:
                on_activate()
            connection.disconnectFromServer()
            connection.deleteLater()

    server.newConnection.connect(accept_connections)
    return server

if __name__ == "__main__":
    def exception_hook(exctype, value, traceback_obj):
        import traceback
        traceback_str = ''.join(traceback.format_tb(traceback_obj))
        error_msg = f"Unhandled Exception: {value}\n\n{traceback_str}"
        print(error_msg)
        from PyQt6.QtWidgets import QMessageBox
        if QApplication.instance():
            QMessageBox.critical(None, "Crash", error_msg)
        else:
            # If no app, just print (already done)
            pass
        sys.exit(1)

    sys.excepthook = exception_hook

    app = QApplication(sys.argv)

    if "--quit-existing" in sys.argv:
        sys.exit(0 if notify_existing_instance(b"quit") else 1)

    if notify_existing_instance():
        sys.exit(0)

    w = Dashboard()

    def activate_dashboard():
        w.showNormal()
        w.raise_()
        w.activateWindow()

    instance_server = start_instance_server(activate_dashboard, w.close)
    if instance_server is None:
        # Another instance won a simultaneous-launch race after our first probe.
        notify_existing_instance()
        sys.exit(0)
    w.show()
    sys.exit(app.exec())
