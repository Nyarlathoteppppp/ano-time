from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QComboBox, QLineEdit, 
                             QTabWidget, QSpinBox, QDoubleSpinBox, QGridLayout,
                             QScrollArea, QSizePolicy, QSpacerItem, QFormLayout, QApplication,
                             QMessageBox, QTextEdit, QDialog, QLayout)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtGui import QFont, QIcon, QColor, QPixmap
import sys
import os
import sounddevice as sd
from config import config
from runtime_version import current_version
from permission_controller import PermissionController
from session_controller import SessionController
from shortcut_controller import ShortcutController

try:
    from ctypes import c_void_p
    from AppKit import (
        NSBackingStoreBuffered, NSColor, NSPanel,
        NSViewHeightSizable, NSViewWidthSizable,
        NSVisualEffectBlendingModeBehindWindow,
        NSVisualEffectMaterialHUDWindow, NSVisualEffectStateActive,
        NSVisualEffectView, NSWindowBelow,
        NSWindowCollectionBehaviorIgnoresCycle,
        NSWindowCollectionBehaviorTransient,
        NSWindowStyleMaskBorderless,
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
    background-color: rgba(255, 184, 211, 46);
}
QTabWidget::pane {
    border: 1px solid rgba(255, 214, 229, 72);
    background: rgba(255, 207, 224, 28);
    border-radius: 12px;
}
QTabBar::tab {
    background: rgba(255, 220, 232, 28);
    color: #a6adc8;
    padding: 10px 20px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: rgba(247, 168, 201, 220);
    color: #10131c;
    font-weight: bold;
}
QLabel {
    font-size: 14px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: rgba(255, 224, 235, 30);
    border: 1px solid rgba(255, 207, 225, 70);
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
    background-color: rgba(247, 168, 201, 210);
    color: #10131c;
    border: 1px solid rgba(255, 255, 255, 30);
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: rgba(255, 193, 218, 235);
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
        """Keep the shortcut resident when the control center is closed."""
        if not getattr(self, "_force_quit", False):
            event.ignore()
            self.hide()
            return
        self.status_label.setText("Stopping...")
        self.on_stop()
        audio_test = getattr(self, "audio_test_worker", None)
        if audio_test and audio_test.isRunning():
            audio_test.wait(2500)
        shortcut_controller = getattr(self, "shortcut_controller", None)
        if shortcut_controller:
            shortcut_controller.stop()
        if self._native_blur_window is not None:
            self._detach_native_glass()
            self._native_blur_window.close()
            self._native_blur_window = None
            self._native_blur_view = None
        # Force application exit
        QApplication.quit()
        event.accept()

    def request_full_quit(self):
        """Quit for upgrades or an explicit application-level exit."""
        self._force_quit = True
        self.close()

    def showEvent(self, event):
        super().showEvent(event)
        self._install_native_glass()
        self._sync_native_glass()
        # Qt's QNSWindow can be attached one event-loop turn after showEvent.
        QTimer.singleShot(0, self._refresh_native_glass)
        QTimer.singleShot(200, self._refresh_native_glass)

    def changeEvent(self, event):
        super().changeEvent(event)
        if getattr(self, "_native_blur_window", None) is not None:
            QTimer.singleShot(0, self._sync_native_glass)

    def _refresh_native_glass(self):
        self._install_native_glass()
        self._sync_native_glass()

    def hideEvent(self, event):
        self._detach_native_glass()
        super().hideEvent(event)

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
        blur_window.setCanHide_(True)
        blur_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorTransient
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        if hasattr(blur_window, "setExcludedFromWindowsMenu_"):
            blur_window.setExcludedFromWindowsMenu_(True)

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
        effect.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                1.0, 0.58, 0.75, 0.16
            ).CGColor()
        )
        blur_window.contentView().addSubview_(effect)
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
        if not self.isVisible() or self.isMinimized():
            self._detach_native_glass(ns_window)
            return
        blur_window.setFrame_display_(ns_window.frame(), True)
        children = list(ns_window.childWindows() or [])
        if blur_window not in children:
            ns_window.addChildWindow_ordered_(blur_window, NSWindowBelow)

    def _detach_native_glass(self, ns_window=None):
        """Remove the backing panel from Mission Control/window composition."""
        blur_window = getattr(self, "_native_blur_window", None)
        if blur_window is None:
            return
        ns_window = ns_window or self._native_window()
        if ns_window is not None:
            try:
                children = list(ns_window.childWindows() or [])
                if blur_window in children:
                    ns_window.removeChildWindow_(blur_window)
            except Exception:
                pass
        blur_window.orderOut_(None)

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
        # 320 ms proved too strict for normal human double taps. Preserve any
        # explicitly slower setting while migrating the old default to 450 ms.
        self.shortcut_interval = max(0.45, config.shortcut_interval)
        self.setWindowTitle("Ano Time - Control Center")
        self.setMinimumSize(760, 540)
        self.setStyleSheet(STYLESHEET)
        
        # Main Layout
        self.layout = QVBoxLayout()
        self.layout.setSpacing(20)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.setLayout(self.layout)
        
        # Header
        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        mascot = QLabel()
        mascot.setFixedSize(78, 101)
        mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mascot_path = os.path.join(os.path.dirname(__file__), "assets", "ano-mascot.png")
        mascot_pixmap = QPixmap(mascot_path)
        if not mascot_pixmap.isNull():
            # Keep the full-resolution source. Pre-scaling to the label's
            # logical size makes Retina displays upscale a tiny 1x bitmap and
            # visibly blurs the mascot.
            mascot.setPixmap(mascot_pixmap)
            mascot.setScaledContents(True)
        header = QLabel(f"Ano Time  ·  {current_version()}")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #f5a9c7;")
        header_row.addWidget(mascot)
        header_row.addWidget(header)
        header_row.addStretch()
        self.layout.addLayout(header_row)
        
        # Tabs
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        
        self.init_home_tab()
        self.init_audio_tab()
        self.init_transcription_tab()
        self.init_translation_tab()
        self.update_home_summary()

        self.permission_controller = PermissionController(
            self, lambda sample_rate: SystemAudioTestWorker(sample_rate)
        )
        self.session_controller = SessionController(
            self, lambda generation: StartupWorker(generation)
        )
        self.shortcut_controller = ShortcutController(self, STYLESHEET)
        # Compatibility for callers that inspect the underlying native object.
        self.global_shortcut = self.shortcut_controller.shortcut
        self.shortcut_controller.start()
        
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

        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("Input Device（音频来源）:"))
        self.home_device_combo = ReadableComboBox()
        self.home_device_combo.setMinimumWidth(360)
        self.home_device_combo.currentIndexChanged.connect(
            lambda: self._on_input_device_changed(self.home_device_combo)
        )
        input_row.addWidget(self.home_device_combo, 1)
        home_refresh = QPushButton("🔄")
        home_refresh.setFixedWidth(40)
        home_refresh.setToolTip("Refresh input devices")
        home_refresh.clicked.connect(self.populate_devices)
        input_row.addWidget(home_refresh)
        layout.addLayout(input_row)

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
        self.start_btn.setStyleSheet("font-size: 16px; background-color: #f5a9c7; border-radius: 10px;")
        self.start_btn.clicked.connect(self.on_start)
        
        self.stop_btn = QPushButton("⏹ Stop Translator")
        self.stop_btn.setFixedSize(200, 60)
        self.stop_btn.setStyleSheet("font-size: 16px; background-color: #f38ba8; border-radius: 10px;")
        self.stop_btn.clicked.connect(self.on_stop)
        self.stop_btn.hide()

        self.pause_btn = QPushButton("⏸ Pause Translator")
        self.pause_btn.setFixedSize(200, 60)
        self.pause_btn.setStyleSheet(
            "font-size: 16px; background-color: #f9e2af; border-radius: 10px;"
        )
        self.pause_btn.clicked.connect(self.toggle_pipeline_pause)
        self.pause_btn.hide()

        self.log_btn = QPushButton("📄 Open Runtime Log")
        self.log_btn.setFixedSize(200, 38)
        self.log_btn.clicked.connect(self.open_runtime_log)

        self.shortcut_btn = QPushButton("⌃S Shortcut Settings")
        self.shortcut_btn.setFixedSize(240, 38)
        self.shortcut_btn.clicked.connect(self.open_shortcut_settings)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.pause_btn)
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
        controller = getattr(self, "shortcut_controller", None)
        if controller:
            controller.update_button()

    def open_shortcut_settings(self):
        self.shortcut_controller.open_settings()

    def open_accessibility_settings(self):
        self.permission_controller.open_accessibility_settings()

    def on_global_shortcut(self):
        self.shortcut_controller.activated()

    def toggle_pipeline_pause(self):
        if self.pipeline:
            self._set_pipeline_paused(not self.pipeline.is_paused)

    def _set_pipeline_paused(self, paused, update_overlay=True):
        self.session_controller.set_paused(paused, update_overlay)

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
        self.permission_controller.open_system_audio_settings()

    def test_system_audio(self):
        self.permission_controller.test_system_audio()

    def on_system_audio_test_result(self, success, message, peak):
        self.permission_controller.on_system_audio_test_result(success, message, peak)

    def init_audio_tab(self):
        tab = QWidget()
        layout = QGridLayout() # Use Grid for organized form
        layout.setSpacing(15)
        
        # Device Selection
        layout.addWidget(QLabel("Input Device（音频来源）:"), 0, 0)
        self.device_combo = ReadableComboBox()
        self.populate_devices()
        self.device_combo.currentIndexChanged.connect(
            lambda: self._on_input_device_changed(self.device_combo)
        )
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
        self.tabs.addTab(tab, "🔧 Legacy Audio")
        
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
        for label, code in (
            ("Auto Detect（自动检测） · auto", "auto"),
            ("English（英语） · en", "en"),
            ("Chinese（中文） · zh", "zh"),
            ("Vietnamese（越南语） · vi", "vi"),
            ("Japanese（日语） · ja", "ja"),
            ("Korean（韩语） · ko", "ko"),
            ("Spanish（西班牙语） · es", "es"),
            ("French（法语） · fr", "fr"),
            ("German（德语） · de", "de"),
            ("Russian（俄语） · ru", "ru"),
            ("Arabic（阿拉伯语） · ar", "ar"),
            ("Portuguese（葡萄牙语） · pt", "pt"),
            ("Italian（意大利语） · it", "it"),
        ):
            self.source_language.addItem(label, code)
        source_lang = config.source_language if config.source_language else "auto"
        source_index = self.source_language.findData(source_lang)
        if source_index >= 0:
            self.source_language.setCurrentIndex(source_index)
        else:
            self.source_language.setCurrentText(source_lang)
        layout.addRow("Source Language（原文语言）:", self.source_language)
        
        # Update UI based on initial backend
        self._on_backend_changed(config.asr_backend)
        
        tab.setLayout(layout)
        self.tabs.addTab(tab, "📝 ASR · 语音识别")
    
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
        for label, value in (
            ("Simplified Chinese（简体中文）", "Chinese"),
            ("English（英语）", "English"),
            ("Japanese（日语）", "Japanese"),
            ("French（法语）", "French"),
            ("Spanish（西班牙语）", "Spanish"),
            ("German（德语）", "German"),
            ("Korean（韩语）", "Korean"),
        ):
            self.target_lang.addItem(label, value)
        self.target_lang.setEditable(True)
        target_index = self.target_lang.findData(config.target_lang)
        if target_index >= 0:
            self.target_lang.setCurrentIndex(target_index)
        else:
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
        self.tabs.addTab(tab, "🌐 AI · 翻译")

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
        items = [
            ("Auto (Default)", "auto"),
            ("System Audio (ScreenCaptureKit — videos/apps)", "system"),
        ]
        try:
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if d['max_input_channels'] > 0:
                    name = f"[{i}] {d['name']}"
                    items.append((name, i))
        except Exception as e:
            items.append((f"Error: {e}", None))

        selected = (
            self.device_combo.currentData()
            if hasattr(self, "device_combo") and self.device_combo.count()
            else config.device_index
        )
        if selected is None:
            selected = "auto"
        for combo in (
            getattr(self, "device_combo", None),
            getattr(self, "home_device_combo", None),
        ):
            if combo is None:
                continue
            combo.blockSignals(True)
            combo.clear()
            for name, data in items:
                combo.addItem(name, data)
            index = combo.findData(selected)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        self.update_home_summary()

    def _on_input_device_changed(self, source_combo):
        selected = source_combo.currentData()
        other = (
            self.home_device_combo
            if source_combo is self.device_combo
            else self.device_combo
        )
        index = other.findData(selected)
        if index >= 0 and other.currentIndex() != index:
            other.blockSignals(True)
            other.setCurrentIndex(index)
            other.blockSignals(False)
        self.update_home_summary()
        if self._session_state == "running":
            self.status_label.setText(
                "Input device changed · Stop and Launch again to apply"
            )

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
        cp.set(
            "transcription", "source_language",
            str(self.source_language.currentData() or self.source_language.currentText()),
        )
        
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
        cp.set(
            "translation", "target_lang",
            str(self.target_lang.currentData() or self.target_lang.currentText()),
        )
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
        self.session_controller.start()

    def on_pipeline_ready(self, generation, pipeline):
        self.session_controller.pipeline_ready(generation, pipeline)

    def on_pipeline_error(self, message):
        self.session_controller.pipeline_error(message)

    def on_stop(self):
        self.session_controller.stop()

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


def start_instance_server(on_activate, on_quit, on_toggle=None):
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
            elif command == b"toggle" and on_toggle is not None:
                on_toggle()
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
    app.setQuitOnLastWindowClosed(False)

    if "--quit-existing" in sys.argv:
        sys.exit(0 if notify_existing_instance(b"quit") else 1)

    if notify_existing_instance():
        sys.exit(0)

    w = Dashboard()

    def activate_dashboard():
        import time
        from runtime_log import log_stage
        started = time.perf_counter()
        previous_state = "minimized" if w.isMinimized() else "visible"
        w.showNormal()
        w.raise_()
        w.activateWindow()
        QTimer.singleShot(
            0,
            lambda: log_stage(
                "dashboard_restore",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                previous_state=previous_state,
                session_state=w._session_state,
            ),
        )

    instance_server = start_instance_server(
        activate_dashboard,
        w.request_full_quit,
        w.on_global_shortcut,
    )
    if instance_server is None:
        # Another instance won a simultaneous-launch race after our first probe.
        notify_existing_instance()
        sys.exit(0)
    from runtime_log import begin_runtime_session
    begin_runtime_session(reset=True)
    w.show()
    sys.exit(app.exec())
