from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QLineEdit,
                             QTabWidget, QGridLayout,
                             QScrollArea, QSizePolicy, QSpacerItem, QFormLayout, QApplication,
                             QMessageBox, QTextEdit, QDialog, QLayout, QInputDialog)
from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon, QColor, QPixmap
import sys
import os
import sounddevice as sd
from config import config
from runtime_version import current_version
from permission_controller import PermissionController
from session_controller import SessionController
from shortcut_controller import ShortcutController
from api_test_controller import ApiTestController
from dashboard_support.app_runtime import (
    notify_existing_instance,
    start_instance_server,
)
from dashboard_support.style import STYLESHEET
from dashboard_support.widgets import ReadableComboBox
from dashboard_support.workers import (
    ModelListWorker,
    StartupWorker,
    SystemAudioTestWorker,
)
from dashboard_support.settings_repository import DashboardSettingsRepository
from dashboard_support.settings_snapshot import (
    AudioSettings,
    DashboardSettingsSnapshot,
    ProviderSettings,
    TranscriptionSettings,
    TranslationSettings,
)
from dashboard_support.panels import AsrPanel, AudioPanel, DEFAULT_AUDIO_SETTINGS

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

class Dashboard(QWidget):
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    def _should_quit_for_close_event(self, event):
        return bool(getattr(self, "_force_quit", False) or event.spontaneous())

    def closeEvent(self, event):
        """Treat the macOS red close button as an explicit application quit."""
        # QWidget.close() creates a non-spontaneous event and is also used by
        # embedded launchers/tests for ownership cleanup. A title-bar close is
        # delivered by the window system as a spontaneous event.
        if not self._should_quit_for_close_event(event):
            event.ignore()
            self.hide()
            return
        self._force_quit = True
        self.status_label.setText("Stopping...")
        self.on_stop()
        audio_test = getattr(self, "audio_test_worker", None)
        if audio_test and audio_test.isRunning():
            audio_test.wait(2500)
        api_test_controller = getattr(self, "api_test_controller", None)
        if api_test_controller:
            api_test_controller.stop()
        model_refresh_worker = getattr(self, "model_refresh_worker", None)
        if model_refresh_worker and model_refresh_worker.isRunning():
            model_refresh_worker.requestInterruption()
            model_refresh_worker.wait(5500)
        shortcut_controller = getattr(self, "shortcut_controller", None)
        if shortcut_controller:
            shortcut_controller.stop()
        if self._native_blur_window is not None:
            self._detach_native_glass()
            self._native_blur_window.close()
            self._native_blur_window = None
            self._native_blur_view = None
        # Exit after Qt has finished dispatching this close event. Immediate
        # teardown here can destroy the shared QApplication re-entrantly.
        QTimer.singleShot(0, QApplication.quit)
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
        self.model_refresh_worker = None
        self.pipeline = None
        self.overlay_window = None
        self._settings_ready = False
        self._settings_dirty = False
        self.shortcut_enabled = config.shortcut_enabled
        self._diagnostics_active = config.diagnostics_enabled
        # 320 ms proved too strict for normal human double taps. Preserve any
        # explicitly slower setting while migrating the old default to 450 ms.
        self.shortcut_interval = max(0.45, config.shortcut_interval)
        self.setWindowTitle("Anotime - Control Center")
        self.setMinimumSize(900, 600)
        self.setStyleSheet(STYLESHEET)
        
        # Main Layout
        self.layout = QVBoxLayout()
        self.layout.setSpacing(20)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.setLayout(self.layout)
        
        # Header
        header_row = QGridLayout()
        header_row.setHorizontalSpacing(10)
        header_row.setVerticalSpacing(0)
        header_row.setColumnMinimumWidth(0, 100)
        header_row.setColumnStretch(1, 1)
        header_row.setColumnMinimumWidth(2, 100)
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
        header = QLabel("· AnoTime ·")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("font-size: 28px; font-weight: bold; color: #f5a9c7;")
        header_row.addWidget(
            mascot,
            0,
            0,
            1,
            1,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        header_row.addWidget(header, 0, 1)
        trailing_mascot = QLabel()
        trailing_mascot.setFixedSize(90, 101)
        trailing_mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        trailing_path = os.path.join(
            os.path.dirname(__file__), "assets", "ano2-mascot.png"
        )
        trailing_pixmap = QPixmap(trailing_path)
        if not trailing_pixmap.isNull():
            trailing_mascot.setPixmap(trailing_pixmap)
            trailing_mascot.setScaledContents(True)
        header_row.addWidget(
            trailing_mascot,
            0,
            2,
            1,
            1,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        self.layout.addLayout(header_row)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setIconSize(QSize(48, 48))
        self.layout.addWidget(self.tabs)
        
        self.init_home_tab()
        self.init_audio_tab()
        self.init_transcription_tab()
        self.init_translation_tab()
        self.update_home_summary()
        self._saved_secrets = {
            "api.default": config.api_key,
            "providers.deepseek": self.provider_keys.get("DeepSeek Official", ""),
            "providers.siliconflow": self.provider_keys.get("SiliconFlow", ""),
            "providers.qwen_mt": self.qwen_fallback_key.text(),
            "providers.groq": self.groq_api_key.text(),
            "providers.gemini": self.gemini_api_key.text(),
            "providers.cloudflare": self.cloudflare_api_token.text(),
        }
        self._connect_settings_dirty_signals()
        self._settings_ready = True

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
        self.build_label = QLabel(f"Build {current_version()}")
        self.build_label.setStyleSheet("font-size: 10px; color: #7f849c;")
        footer.addWidget(self.build_label)
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

        self.pending_settings_label = QLabel()
        self.pending_settings_label.setWordWrap(True)
        self.pending_settings_label.setStyleSheet(
            "font-size: 13px; color: #f9e2af; padding: 3px 0;"
        )
        self.pending_settings_label.hide()
        layout.addWidget(self.pending_settings_label)

        self.apply_hint = QLabel(
            "生效规则：启动/暂停/停止立即生效；普通设置保存后重新 Launch 生效；"
            "Diagnostics 保存后重启 App 生效。"
        )
        self.apply_hint.setWordWrap(True)
        self.apply_hint.setStyleSheet(
            "font-size: 12px; color: #bac2de; "
            "background: rgba(255,255,255,10); border-radius: 7px; padding: 7px 10px;"
        )
        layout.addWidget(self.apply_hint)

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

        display_apply_hint = QLabel("保存后重新 Launch 生效")
        display_apply_hint.setStyleSheet("font-size: 11px; color: #f9e2af;")
        layout.addWidget(display_apply_hint)

        self.notch_help = QLabel(
            "刘海操作：点击刘海可按 小 → 中 → 大 循环切换；"
            "小模式显示 1 条，中模式显示 2 条，大模式显示 3 条字幕。"
        )
        self.notch_help.setWordWrap(True)
        self.notch_help.setStyleSheet(
            "font-size: 13px; color: #bac2de; "
            "background-color: rgba(255, 255, 255, 10); "
            "border: 1px solid rgba(255, 255, 255, 25); "
            "border-radius: 8px; padding: 9px 12px;"
        )
        layout.addWidget(self.notch_help)
        
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

        self.log_btn = QPushButton("Open Runtime Log")
        self.log_btn.setFixedSize(200, 38)
        self.log_btn.clicked.connect(self.open_runtime_log)
        self.log_btn.setEnabled(self._diagnostics_active)
        if not self._diagnostics_active:
            self.log_btn.setText("Runtime Log (Off)")

        self.diagnostics_checkbox = QCheckBox(
            "Diagnostics（诊断埋点，仅排查时开启）"
        )
        self.diagnostics_checkbox.setChecked(config.diagnostics_enabled)
        self.diagnostics_checkbox.setToolTip(
            "Default: Off. Applies after a full app restart.\n"
            "When off, no log queue, log writer, or resource sampler runs."
        )

        self.transcript_recording_checkbox = QCheckBox(
            "自动保存双语记录（保留 3 天）"
        )
        self.transcript_recording_checkbox.setChecked(
            config.auto_save_transcripts
        )
        self.transcript_recording_checkbox.setToolTip(
            "每次启动翻译后，在“文稿/Anotime Records”生成带日期时间的双语 TXT。\n"
            "写入在独立后台线程完成，不阻塞实时字幕；超过 3 天自动删除。"
        )

        self.shortcut_btn = QPushButton("⌃S Shortcut Settings")
        self.shortcut_btn.setFixedSize(240, 38)
        self.shortcut_btn.clicked.connect(self.open_shortcut_settings)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)
        layout.addWidget(self.log_btn)
        layout.addWidget(self.diagnostics_checkbox)
        layout.addWidget(self.transcript_recording_checkbox)
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
        self.tabs.addTab(
            scroll,
            QIcon(os.path.join(os.path.dirname(__file__), "assets", "tab-home-ano.png")),
            "Home",
        )

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
        if hasattr(self, "translation_workflow"):
            workflow = self.translation_workflow.currentData()
            bridge = (
                self.bridge_provider.currentData()
                if hasattr(self, "bridge_provider") else "off"
            )
            if workflow == "apple_only":
                model = "Apple on-device only"
            elif workflow == "smart_hybrid":
                model = (
                    "Apple → Groq → Gemini/GLM → Qwen-MT"
                    if bridge == "groq"
                    else "Apple → Gemini/GLM → Qwen-MT"
                )
            else:
                prefix = "Apple → Groq → " if bridge == "groq" else "Apple → "
                model = prefix + self.model.currentText()
        else:
            model = config.model
        self.translation_summary.setText(model)

    def _connect_settings_dirty_signals(self):
        """Mark saved runtime settings that differ from the active session."""
        combos = (
            self.device_combo,
            self.home_device_combo,
            self.display_mode,
            self.asr_backend,
            self.whisper_model,
            self.funasr_model,
            self.device_type,
            self.compute_type,
            self.source_language,
            self.translation_workflow,
            self.bridge_provider,
            self.provider,
            self.model,
            self.target_lang,
            self.fast_translation_backend,
        )
        for combo in combos:
            combo.currentTextChanged.connect(self._mark_settings_dirty)

        for spinbox in (
            self.sample_rate,
            self.silence_thresh,
            self.silence_dur,
            self.update_interval,
        ):
            spinbox.valueChanged.connect(self._mark_settings_dirty)

        for field in (
            self.api_key,
            self.base_url,
            self.groq_api_key,
            self.gemini_api_key,
            self.cloudflare_account_id,
            self.cloudflare_api_token,
            self.qwen_fallback_key,
            self.qwen_fallback_url,
            self.translation_domain,
        ):
            field.textChanged.connect(self._mark_settings_dirty)

        self.diagnostics_checkbox.toggled.connect(self._mark_settings_dirty)
        self.transcript_recording_checkbox.toggled.connect(
            self._mark_settings_dirty
        )

    def _mark_settings_dirty(self, *_):
        if not self._settings_ready:
            return
        self._settings_dirty = True
        self.pending_settings_label.show()
        if self._session_state == "running":
            message = "Settings changed · Stop and Launch again to apply"
        else:
            message = "Unsaved settings · Launch saves and applies automatically"
        self.pending_settings_label.setText(message)

    def _settings_saved(self):
        """Update the pending-settings hint without replacing runtime status."""
        if self._session_state == "running" and self._settings_dirty:
            self._settings_dirty = True
            self.pending_settings_label.setText(
                "Settings saved · Stop and Launch again to apply"
            )
            self.pending_settings_label.show()
            return
        self._settings_dirty = False
        self.pending_settings_label.clear()
        self.pending_settings_label.hide()

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
        panel = AudioPanel(
            config,
            on_device_changed=self._on_input_device_changed,
            on_refresh=self.populate_devices,
            on_use_system_audio=self.use_system_audio,
            on_test_system_audio=self.test_system_audio,
            on_open_permissions=self.open_system_audio_settings,
            on_restore_defaults=self.restore_audio_defaults,
        )
        self.audio_panel = panel
        self.device_combo = panel.device_combo
        self.sample_rate = panel.sample_rate
        self.silence_thresh = panel.silence_thresh
        self.silence_dur = panel.silence_dur
        self.update_interval = panel.update_interval
        self.use_system_audio_btn = panel.use_system_audio_btn
        self.test_system_audio_btn = panel.test_system_audio_btn
        self.open_audio_permission_btn = panel.open_audio_permission_btn
        self.restore_audio_defaults_btn = panel.restore_audio_defaults_btn
        self.audio_test_status = panel.audio_test_status
        self.populate_devices()
        self.tabs.addTab(
            panel,
            QIcon(os.path.join(os.path.dirname(__file__), "assets", "tab-audio-ano.png")),
            "Audio",
        )

    def restore_audio_defaults(self):
        """Restore only documented Audio defaults; Save remains explicit."""
        self.audio_panel.restore_defaults()
        index = self.home_device_combo.findData(
            DEFAULT_AUDIO_SETTINGS["device_index"]
        )
        if index >= 0:
            self.home_device_combo.blockSignals(True)
            self.home_device_combo.setCurrentIndex(index)
            self.home_device_combo.blockSignals(False)

        self.update_home_summary()
        if self._session_state == "running":
            self.status_label.setText(
                "Audio defaults restored · Stop, save, and launch again to apply"
            )

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
        """Fetch model names without blocking the Qt interface."""
        if self.model_refresh_worker and self.model_refresh_worker.isRunning():
            return
        self.refresh_models_btn.setEnabled(False)
        self.refresh_models_btn.setText("…")
        worker = ModelListWorker(
            api_key=self.api_key.text() or "dummy-key-for-local",
            base_url=self.base_url.text() or None,
        )
        self.model_refresh_worker = worker
        worker.loaded.connect(self._on_model_list_loaded)
        worker.failed.connect(self._on_model_list_failed)
        worker.finished.connect(self._on_model_list_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_model_list_loaded(self, model_ids):
        current_model = self.model.currentText()
        self.model.blockSignals(True)
        self.model.clear()
        if model_ids:
            self.model.addItems(sorted(model_ids))
            index = self.model.findText(current_model)
            if index >= 0:
                self.model.setCurrentIndex(index)
            else:
                self.model.setCurrentText(current_model)
            self.status_label.setText(f"✅ Loaded {len(model_ids)} models")
            self.status_label.setStyleSheet("font-size: 18px; color: #a6e3a1;")
        else:
            self.model.addItem(current_model)
            self.status_label.setText("⚠️ No models found")
            self.status_label.setStyleSheet("font-size: 18px; color: #fab387;")
        self.model.blockSignals(False)

    def _on_model_list_failed(self, error_msg):
        if not self.model.currentText():
            self.model.addItem(config.model)
        compact = " ".join(str(error_msg).split())
        self.status_label.setText(f"❌ Model refresh failed: {compact[:80]}")
        self.status_label.setStyleSheet("font-size: 16px; color: #f38ba8;")
        print(f"[Dashboard] Model refresh error: {compact}")

    def _on_model_list_finished(self):
        self.model_refresh_worker = None
        self.refresh_models_btn.setEnabled(True)
        self.refresh_models_btn.setText("🔄")

    def init_transcription_tab(self):
        panel = AsrPanel(config)
        self.asr_panel = panel
        # Compatibility aliases keep controllers, settings collection, and
        # third-party callers stable while the Dashboard becomes componentized.
        self.transcription_layout = panel.form_layout
        self.asr_backend = panel.asr_backend
        self.backend_hint = panel.backend_hint
        self.whisper_model = panel.whisper_model
        self.funasr_model = panel.funasr_model
        self.device_type = panel.device_type
        self.compute_type = panel.compute_type
        self.source_language = panel.source_language
        self.asr_backend.currentTextChanged.connect(self.update_home_summary)
        self.tabs.addTab(
            panel,
            QIcon(os.path.join(os.path.dirname(__file__), "assets", "tab-asr-ano.png")),
            "ASR · 语音识别",
        )
    
    def _on_backend_changed(self, backend):
        self.asr_panel.on_backend_changed(backend)

    def _set_transcription_row_visible(self, field, visible):
        self.asr_panel.set_row_visible(field, visible)
    
    def _check_funasr_mps_compatibility(self):
        self.asr_panel.check_funasr_mps_compatibility()
    
    def _show_mps_float32_warning(self):
        self.asr_panel.show_mps_float32_warning()
    
    def _on_device_changed(self, device):
        self.asr_panel.on_device_changed(device)
    
    def _on_quantization_changed(self, quantization):
        self.asr_panel.on_quantization_changed(quantization)

    def init_translation_tab(self):
        tab = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.setVerticalSpacing(12)
        self.translation_layout = layout

        translation_apply_hint = QLabel(
            "生效时间：流程、模型、密钥和目标语言保存后，重新 Launch 生效。"
        )
        translation_apply_hint.setWordWrap(True)
        translation_apply_hint.setStyleSheet(
            "color: #f9e2af; background: rgba(255,255,255,10); "
            "border-radius: 7px; padding: 8px 10px;"
        )
        layout.addRow(translation_apply_hint)

        self.translation_workflow = ReadableComboBox()
        self.translation_workflow.addItem(
            "Smart Hybrid（智能混合 · 推荐）", "smart_hybrid"
        )
        self.translation_workflow.addItem("Single Model（单模型）", "single_model")
        self.translation_workflow.addItem("Apple Only（仅 Apple 本地）", "apple_only")
        workflow_index = self.translation_workflow.findData(
            config.translation_workflow
        )
        self.translation_workflow.setCurrentIndex(max(0, workflow_index))
        layout.addRow("Workflow（翻译流程）:", self.translation_workflow)

        workflow_card = QFrame()
        workflow_card.setObjectName("WorkflowPreviewCard")
        workflow_card.setStyleSheet(
            "QFrame#WorkflowPreviewCard {"
            "background: rgba(255,255,255,14);"
            "border: 1px solid rgba(255,255,255,30);"
            "border-radius: 9px;"
            "}"
        )
        workflow_card_layout = QVBoxLayout(workflow_card)
        workflow_card_layout.setContentsMargins(12, 10, 12, 10)
        workflow_card_layout.setSpacing(5)
        workflow_title = QLabel("Active Chain（当前链路）")
        workflow_title.setStyleSheet("font-weight: 600; color: #cdd6f4;")
        self.workflow_preview = QLabel()
        self.workflow_preview.setWordWrap(True)
        self.workflow_preview.setMinimumHeight(48)
        self.workflow_preview.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.workflow_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        self.workflow_preview.setStyleSheet(
            "color: #a6e3a1; font-weight: 600;"
        )
        workflow_card_layout.addWidget(workflow_title)
        workflow_card_layout.addWidget(self.workflow_preview)
        layout.addRow(workflow_card)

        self.bridge_provider = ReadableComboBox()
        self.bridge_provider.addItem("Off（关闭）", "off")
        self.bridge_provider.addItem("Groq GPT-OSS 20B（快速过渡）", "groq")
        bridge_index = self.bridge_provider.findData(config.bridge_provider)
        self.bridge_provider.setCurrentIndex(max(0, bridge_index))
        layout.addRow("Bridge（桥接翻译，可选）:", self.bridge_provider)

        self.provider = ReadableComboBox()
        self.provider.addItems([
            "Alibaba Cloud Qwen-MT",
            "DeepSeek Official",
            "SiliconFlow",
            "OpenAI",
            "Google Gemini",
            "Groq",
            "OpenRouter",
            "Custom OpenAI-Compatible",
        ])
        configured_single_provider = (
            "Custom OpenAI-Compatible"
            if config.single_provider == "Custom"
            else config.single_provider
        )
        self.provider.setCurrentText(configured_single_provider)
        self._current_provider = self.provider.currentText()
        self.provider_keys = {
            "DeepSeek Official": config.deepseek_api_key or config.api_key,
            "SiliconFlow": config.siliconflow_api_key,
            "Alibaba Cloud Qwen-MT": config.qwen_mt_api_key,
            "OpenAI": config.api_key,
            "Google Gemini": config.api_key,
            "Groq": config.groq_api_key or config.api_key,
            "OpenRouter": config.api_key,
            "Custom OpenAI-Compatible": config.api_key,
        }
        self.provider_urls = {
            "DeepSeek Official": "https://api.deepseek.com",
            "SiliconFlow": "https://api.siliconflow.cn/v1",
            "Alibaba Cloud Qwen-MT": config.qwen_mt_base_url,
            "OpenAI": "https://api.openai.com/v1",
            "Google Gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "Groq": "https://api.groq.com/openai/v1",
            "OpenRouter": "https://openrouter.ai/api/v1",
            "Custom OpenAI-Compatible": config.api_base_url or "",
        }
        self.provider_model_presets = {
            "Alibaba Cloud Qwen-MT": ["qwen-mt-flash"],
            "DeepSeek Official": ["deepseek-v4-flash", "deepseek-chat"],
            "SiliconFlow": [
                "deepseek-ai/DeepSeek-V4-Flash",
                "Qwen/Qwen3.5-4B",
                "Qwen/Qwen3-8B",
                "Qwen/Qwen3-30B-A3B-Instruct-2507",
            ],
            "OpenAI": ["gpt-5-mini", "gpt-5-nano"],
            "Google Gemini": ["gemini-2.5-flash-lite", "gemini-2.5-flash"],
            "Groq": ["openai/gpt-oss-20b"],
            "OpenRouter": ["openai/gpt-5-mini", "google/gemini-2.5-flash-lite"],
            "Custom OpenAI-Compatible": [],
        }
        self.provider_selected_models = {configured_single_provider: config.model}
        self.provider.currentTextChanged.connect(self._on_translation_provider_changed)
        layout.addRow("Final Provider（最终翻译服务）:", self.provider)
        
        self.api_key = QLineEdit(
            self.provider_keys.get(self.provider.currentText(), config.api_key)
        )
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
        
        self.qwen_fallback_key = QLineEdit(config.qwen_mt_api_key)
        self.qwen_fallback_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.qwen_fallback_key.setPlaceholderText("Alibaba Cloud Qwen-MT key")
        layout.addRow("Qwen-MT Key（付费兜底密钥）:", self.qwen_fallback_key)

        self.qwen_fallback_url = QLineEdit(config.qwen_mt_base_url)
        self.qwen_fallback_url.setPlaceholderText(
            "https://{WorkspaceId}.maas.aliyuncs.com/compatible-mode/v1"
        )
        layout.addRow("Qwen-MT URL（付费兜底接口）:", self.qwen_fallback_url)

        self.base_url = QLineEdit(
            self.provider_urls.get(self.provider.currentText(), config.api_base_url or "")
        )
        self.base_url.setPlaceholderText("https://api.openai.com/v1")
        layout.addRow("Base URL（API 接口地址）:", self.base_url)
        
        # Model selection with refresh button
        model_layout = QHBoxLayout()
        self.model = ReadableComboBox()
        self.model.setEditable(True)
        self.model.addItem(config.model)
        self.model.setToolTip(
            "可以选择预设，也可以直接输入任意服务支持的模型 ID。"
        )
        self.model.currentTextChanged.connect(self.update_home_summary)
        model_layout.addWidget(self.model)

        self.add_custom_model_btn = QPushButton("＋")
        self.add_custom_model_btn.setFixedWidth(40)
        self.add_custom_model_btn.setToolTip("Add a custom model ID（添加自定义模型）")
        self.add_custom_model_btn.clicked.connect(self.add_custom_model)
        model_layout.addWidget(self.add_custom_model_btn)
        
        self.refresh_models_btn = QPushButton("🔄")
        self.refresh_models_btn.setFixedWidth(40)
        self.refresh_models_btn.setToolTip("Refresh model list from API")
        self.refresh_models_btn.clicked.connect(self.refresh_model_list)
        model_layout.addWidget(self.refresh_models_btn)
        self.model_container = QWidget()
        self.model_container.setLayout(model_layout)
        layout.addRow("Model（翻译模型）:", self.model_container)

        self.api_test_provider = ReadableComboBox()
        layout.addRow("Test Target（测速服务）:", self.api_test_provider)

        self.api_test_btn = QPushButton("Test API · 5 Requests（测试五条）")
        self.api_test_btn.setToolTip(
            "Send five fixed Computer Science/AI translation requests and measure "
            "first-token and total latency. This consumes five API requests."
        )
        layout.addRow("API Speed Test（接口测速）:", self.api_test_btn)

        self.api_test_results = QTextEdit()
        self.api_test_results.setReadOnly(True)
        self.api_test_results.setMaximumHeight(180)
        self.api_test_results.setPlaceholderText(
            "逐条显示首字延迟、总耗时和翻译结果；测试不会进入课堂字幕。"
        )
        layout.addRow("Test Results（测速结果）:", self.api_test_results)
        self.api_test_controller = ApiTestController(self)
        self.api_test_btn.clicked.connect(self.api_test_controller.start)
        
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

        self.translation_workflow.currentIndexChanged.connect(
            self._on_translation_workflow_changed
        )
        self.bridge_provider.currentIndexChanged.connect(
            self._on_translation_workflow_changed
        )
        for field in (
            self.api_key,
            self.base_url,
            self.groq_api_key,
            self.gemini_api_key,
            self.cloudflare_account_id,
            self.cloudflare_api_token,
            self.qwen_fallback_key,
            self.qwen_fallback_url,
        ):
            field.textChanged.connect(self._on_translation_workflow_changed)
        self._on_translation_provider_changed(self.provider.currentText())
        self._on_translation_workflow_changed()
        
        content = QWidget()
        content.setLayout(layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        self.tabs.addTab(
            tab,
            QIcon(
                os.path.join(
                    os.path.dirname(__file__), "assets", "tab-translation-ano.png"
                )
            ),
            "AI · 翻译",
        )

    def _on_translation_provider_changed(self, provider):
        if hasattr(self, "api_key"):
            self.provider_keys[self._current_provider] = self.api_key.text()
            self.provider_urls[self._current_provider] = self.base_url.text()
            self.provider_selected_models[self._current_provider] = (
                self.model.currentText().strip()
            )
            self.api_key.setText(self.provider_keys.get(provider, ""))
        self._current_provider = provider
        if hasattr(self, "base_url"):
            self.api_key.setEnabled(True)
            self.base_url.setEnabled(True)
            self.model.setEnabled(True)
            self.refresh_models_btn.setEnabled(True)
        if provider == "DeepSeek Official":
            self.base_url.setText("https://api.deepseek.com")
        elif provider == "SiliconFlow":
            self.base_url.setText("https://api.siliconflow.cn/v1")
        elif provider == "Alibaba Cloud Qwen-MT":
            self.base_url.setText(self.provider_urls.get(provider, ""))
            self.base_url.setPlaceholderText(
                "https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
            )
        else:
            self.base_url.setText(self.provider_urls.get(provider, self.base_url.text()))
        self._populate_provider_models(provider)
        self._on_translation_workflow_changed()

    def _populate_provider_models(self, provider):
        """Expose useful presets without restricting manually entered model IDs."""
        current = self.model.currentText().strip()
        presets = list(self.provider_model_presets.get(provider, ()))
        preferred = self.provider_selected_models.get(provider, "").strip()
        if not preferred:
            preferred = presets[0] if presets else current
        self.model.blockSignals(True)
        self.model.clear()
        for model_id in presets:
            self.model.addItem(model_id)
        if preferred and self.model.findText(preferred) < 0:
            self.model.addItem(preferred)
        self.model.setCurrentText(preferred)
        self.model.blockSignals(False)
        self.provider_selected_models[provider] = preferred
        self.update_home_summary()

    def add_custom_model(self):
        model_id, accepted = QInputDialog.getText(
            self,
            "Add Custom Model",
            "Model ID（填写服务商文档中的完整模型 ID）:",
        )
        model_id = model_id.strip()
        if not accepted or not model_id:
            return
        if self.model.findText(model_id) < 0:
            self.model.addItem(model_id)
        self.model.setCurrentText(model_id)
        self._mark_settings_dirty()

    def _on_translation_workflow_changed(self, *_):
        if not hasattr(self, "translation_workflow"):
            return
        workflow = self.translation_workflow.currentData() or "smart_hybrid"
        bridge = self.bridge_provider.currentData() or "off"
        apple_only = workflow == "apple_only"
        single = workflow == "single_model"
        smart = workflow == "smart_hybrid"

        self.bridge_provider.setEnabled(not apple_only)
        for widget in (self.provider, self.api_key, self.base_url, self.model_container):
            self._set_translation_row_visible(widget, single)
        self._set_translation_row_visible(
            self.groq_api_key, not apple_only and bridge == "groq"
        )
        for widget in (
            self.gemini_api_key,
            self.cloudflare_account_id,
            self.cloudflare_api_token,
            self.qwen_fallback_key,
            self.qwen_fallback_url,
        ):
            self._set_translation_row_visible(widget, smart)
        for widget in (
            self.api_test_provider,
            self.api_test_btn,
            self.api_test_results,
        ):
            self._set_translation_row_visible(widget, not apple_only)
        self.fast_translation_backend.setEnabled(not apple_only)
        if apple_only:
            self.fast_translation_backend.setCurrentText("apple")
            preview = "Apple ASR → Apple Translation（完全本地）"
        elif smart:
            middle = "Groq → " if bridge == "groq" else ""
            preview = f"Apple → {middle}Gemini/GLM → Qwen-MT"
        else:
            middle = "Groq → " if bridge == "groq" else ""
            preview = f"Apple → {middle}{self.provider.currentText()}"
        missing = []
        if not apple_only and bridge == "groq" and not self.groq_api_key.text().strip():
            missing.append("Groq Key")
        if smart:
            has_gemini = bool(self.gemini_api_key.text().strip())
            has_glm = bool(
                self.cloudflare_account_id.text().strip()
                and self.cloudflare_api_token.text().strip()
            )
            if not (has_gemini or has_glm):
                missing.append("Gemini 或 GLM")
            if not (
                self.qwen_fallback_key.text().strip()
                and self.qwen_fallback_url.text().strip()
            ):
                missing.append("Qwen-MT 兜底")
        elif single and not (
            self.api_key.text().strip() and self.base_url.text().strip()
        ):
            missing.append("最终模型 API")
        if missing:
            preview += "\n⚠ Missing: " + "、".join(missing)
            color = "#f9e2af"
        else:
            preview += "\n✓ Configuration ready"
            color = "#a6e3a1"
        self.workflow_preview.setStyleSheet(
            f"color: {color}; font-weight: 600;"
        )
        self.workflow_preview.setText(preview)
        self.api_test_controller.refresh_targets()
        self.update_home_summary()

    def _set_translation_row_visible(self, widget, visible):
        widget.setVisible(bool(visible))
        label = self.translation_layout.labelForField(widget)
        if label:
            label.setVisible(bool(visible))

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

    def collect_settings(self):
        """Create an immutable settings snapshot from the current widgets."""
        workflow = self.translation_workflow.currentData() or "smart_hybrid"
        bridge_provider = (
            "off" if workflow == "apple_only"
            else self.bridge_provider.currentData() or "off"
        )
        if workflow == "single_model":
            self.provider_keys[self.provider.currentText()] = self.api_key.text()
            self.provider_urls[self.provider.currentText()] = self.base_url.text()
        qwen_key = (
            self.api_key.text()
            if workflow == "single_model"
            and self.provider.currentText() == "Alibaba Cloud Qwen-MT"
            else self.qwen_fallback_key.text()
        )
        qwen_url = (
            self.base_url.text()
            if workflow == "single_model"
            and self.provider.currentText() == "Alibaba Cloud Qwen-MT"
            else self.qwen_fallback_url.text()
        )
        return DashboardSettingsSnapshot(
            audio=AudioSettings(
                device_index=self.device_combo.currentData(),
                sample_rate=self.sample_rate.value(),
                silence_threshold=self.silence_thresh.value(),
                silence_duration=self.silence_dur.value(),
                update_interval=self.update_interval.value(),
            ),
            transcription=TranscriptionSettings(
                backend=self.asr_backend.currentText(),
                whisper_model=self.whisper_model.currentText(),
                funasr_model=self.funasr_model.currentText(),
                device=self.device_type.currentText(),
                compute_type=self.compute_type.currentText(),
                source_language=str(
                    self.source_language.currentData()
                    or self.source_language.currentText()
                ),
            ),
            translation=TranslationSettings(
                workflow=workflow,
                bridge_provider=bridge_provider,
                single_provider=self.provider.currentText(),
                api_key=self.api_key.text(),
                base_url=self.base_url.text(),
                model=self.model.currentText(),
                target_language=str(
                    self.target_lang.currentData() or self.target_lang.currentText()
                ),
                domain=self.translation_domain.text(),
                fast_backend=(
                    "apple"
                    if workflow == "apple_only"
                    else self.fast_translation_backend.currentText()
                ),
            ),
            providers=ProviderSettings(
                deepseek_api_key=self.provider_keys.get("DeepSeek Official", ""),
                siliconflow_api_key=self.provider_keys.get("SiliconFlow", ""),
                qwen_mt_api_key=qwen_key,
                qwen_mt_base_url=qwen_url,
                groq_api_key=self.groq_api_key.text(),
                gemini_api_key=self.gemini_api_key.text(),
                cloudflare_account_id=self.cloudflare_account_id.text(),
                cloudflare_api_token=self.cloudflare_api_token.text(),
            ),
            display_mode=self.display_mode.currentData(),
            shortcut_enabled=self.shortcut_enabled,
            shortcut_interval=self.shortcut_interval,
            diagnostics_enabled=self.diagnostics_checkbox.isChecked(),
            auto_save_transcripts=self.transcript_recording_checkbox.isChecked(),
        )

    def save_config(self, checked=False, show_status=True):
        config_path = os.path.join(os.path.dirname(__file__), "config.ini")
        repository = DashboardSettingsRepository(config_path)
        saved_secret_updates = repository.save(
            self.collect_settings(),
            previous_secrets=self._saved_secrets,
        )
        self._saved_secrets.update(saved_secret_updates)
        config.reload()
        self._settings_saved()
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

if __name__ == "__main__":
    from dashboard_support.app_runtime import run_dashboard

    sys.exit(run_dashboard(Dashboard, config))
