from ui.qt import QtWidgets


QDoubleSpinBox = QtWidgets.QDoubleSpinBox
QGridLayout = QtWidgets.QGridLayout
QHBoxLayout = QtWidgets.QHBoxLayout
QLabel = QtWidgets.QLabel
QLayout = QtWidgets.QLayout
QPushButton = QtWidgets.QPushButton
QSpinBox = QtWidgets.QSpinBox
QWidget = QtWidgets.QWidget

from dashboard_support.widgets import ReadableComboBox


DEFAULT_AUDIO_SETTINGS = {
    "device_index": "auto",
    "sample_rate": 16000,
    "silence_threshold": 0.005,
    "silence_duration": 0.5,
    "update_interval": 0.5,
}


class AudioPanel(QWidget):
    """Audio settings page; host callbacks own permissions and coordination."""

    def __init__(
        self,
        settings,
        *,
        on_device_changed,
        on_refresh,
        on_use_system_audio,
        on_test_system_audio,
        on_open_permissions,
        on_restore_defaults,
        parent=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(15)
        self.grid_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.setLayout(self.grid_layout)
        self._build(
            on_device_changed=on_device_changed,
            on_refresh=on_refresh,
            on_use_system_audio=on_use_system_audio,
            on_test_system_audio=on_test_system_audio,
            on_open_permissions=on_open_permissions,
            on_restore_defaults=on_restore_defaults,
        )

    def _build(self, **callbacks):
        layout = self.grid_layout
        layout.addWidget(QLabel("Input Device（音频来源）:"), 0, 0)
        self.device_combo = ReadableComboBox()
        self.device_combo.currentIndexChanged.connect(
            lambda: callbacks["on_device_changed"](self.device_combo)
        )
        layout.addWidget(self.device_combo, 0, 1)

        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.setFixedWidth(40)
        self.refresh_btn.setMinimumHeight(38)
        self.refresh_btn.clicked.connect(callbacks["on_refresh"])
        layout.addWidget(self.refresh_btn, 0, 2)

        layout.addWidget(QLabel("Sample Rate（采样率）:"), 1, 0)
        self.sample_rate = QSpinBox()
        self.sample_rate.setRange(8000, 48000)
        self.sample_rate.setValue(self.settings.sample_rate)
        self.sample_rate.setToolTip(
            "Apple 语音识别支持 8000 或 16000 Hz；其他数值保存时会自动调整。\n"
            "Whisper、MLX 和 FunASR 可继续使用其他采样率。"
        )
        layout.addWidget(self.sample_rate, 1, 1)

        layout.addWidget(QLabel("Silence Threshold（静音判定阈值）:"), 2, 0)
        self.silence_thresh = QDoubleSpinBox()
        self.silence_thresh.setRange(0.001, 1.0)
        self.silence_thresh.setSingleStep(0.001)
        self.silence_thresh.setDecimals(3)
        self.silence_thresh.setValue(self.settings.silence_threshold)
        layout.addWidget(self.silence_thresh, 2, 1)

        layout.addWidget(QLabel("Silence Duration（持续静音多久才断句，秒）:"), 3, 0)
        self.silence_dur = QDoubleSpinBox()
        self.silence_dur.setValue(self.settings.silence_duration)
        layout.addWidget(self.silence_dur, 3, 1)

        layout.addWidget(QLabel("Live Refresh Interval（临时字幕刷新间隔，秒）:"), 4, 0)
        self.update_interval = QDoubleSpinBox()
        self.update_interval.setRange(0.2, 2.0)
        self.update_interval.setSingleStep(0.1)
        self.update_interval.setDecimals(1)
        self.update_interval.setValue(self.settings.update_interval)
        self.update_interval.setToolTip(
            "Lower values update partial subtitles faster. 0.5 s is recommended for class."
        )
        layout.addWidget(self.update_interval, 4, 1)

        for control in (
            self.device_combo,
            self.sample_rate,
            self.silence_thresh,
            self.silence_dur,
            self.update_interval,
        ):
            control.setMinimumHeight(38)

        action_row = QHBoxLayout()
        self.use_system_audio_btn = QPushButton("Use System Audio")
        self.use_system_audio_btn.setToolTip(
            "Select native ScreenCaptureKit audio from videos and applications"
        )
        self.use_system_audio_btn.clicked.connect(callbacks["on_use_system_audio"])
        self.use_system_audio_btn.setMinimumHeight(42)
        action_row.addWidget(self.use_system_audio_btn)

        self.test_system_audio_btn = QPushButton("Test Permission & Audio")
        self.test_system_audio_btn.clicked.connect(callbacks["on_test_system_audio"])
        self.test_system_audio_btn.setMinimumHeight(42)
        action_row.addWidget(self.test_system_audio_btn)

        self.open_audio_permission_btn = QPushButton("Open Permission Settings")
        self.open_audio_permission_btn.clicked.connect(callbacks["on_open_permissions"])
        self.open_audio_permission_btn.setMinimumHeight(42)
        action_row.addWidget(self.open_audio_permission_btn)

        self.restore_audio_defaults_btn = QPushButton(
            "Restore Audio Defaults（恢复音频默认值）"
        )
        self.restore_audio_defaults_btn.setToolTip(
            "Reset only Audio settings. API, ASR, translation, and display settings stay unchanged."
        )
        self.restore_audio_defaults_btn.clicked.connect(callbacks["on_restore_defaults"])
        self.restore_audio_defaults_btn.setMinimumHeight(42)
        layout.addLayout(action_row, 5, 0, 1, 3)
        layout.addWidget(self.restore_audio_defaults_btn, 6, 0, 1, 3)

        self.audio_test_status = QLabel(
            "System Audio uses macOS ScreenCaptureKit; BlackHole is not required."
        )
        self.audio_test_status.setWordWrap(True)
        self.audio_test_status.setMinimumHeight(52)
        self.audio_test_status.setStyleSheet(
            "color: #a6adc8; background: rgba(255,255,255,14); "
            "padding: 10px; border-radius: 8px;"
        )
        layout.addWidget(self.audio_test_status, 7, 0, 1, 3)
        self.apply_hint = QLabel(
            "生效时间：权限测试立即执行；音频来源和参数保存后重新 Launch 生效。"
        )
        self.apply_hint.setWordWrap(True)
        self.apply_hint.setMinimumHeight(30)
        self.apply_hint.setStyleSheet("font-size: 11px; color: #f9e2af;")
        layout.addWidget(self.apply_hint, 8, 0, 1, 3)
        layout.setRowStretch(9, 1)

    def restore_defaults(self):
        defaults = DEFAULT_AUDIO_SETTINGS
        self.sample_rate.setValue(defaults["sample_rate"])
        self.silence_thresh.setValue(defaults["silence_threshold"])
        self.silence_dur.setValue(defaults["silence_duration"])
        self.update_interval.setValue(defaults["update_interval"])
        index = self.device_combo.findData(defaults["device_index"])
        if index >= 0:
            self.device_combo.blockSignals(True)
            self.device_combo.setCurrentIndex(index)
            self.device_combo.blockSignals(False)
        self.audio_test_status.setText(
            "Audio defaults restored in the control center. Click Save Settings to apply."
        )
        self.audio_test_status.setStyleSheet(
            "color: #a6e3a1; background: rgba(255,255,255,14); "
            "padding: 10px; border-radius: 8px;"
        )
