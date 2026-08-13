from ui.qt import QtWidgets


QFormLayout = QtWidgets.QFormLayout
QLabel = QtWidgets.QLabel
QMessageBox = QtWidgets.QMessageBox
QWidget = QtWidgets.QWidget

from dashboard_support.widgets import ReadableComboBox


class AsrPanel(QWidget):
    """ASR settings page with no dependency on the Dashboard host."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.form_layout = QFormLayout()
        self.form_layout.setVerticalSpacing(14)
        self.setLayout(self.form_layout)
        self._build()

    def _build(self):
        layout = self.form_layout
        self.apply_hint = QLabel(
            "生效时间：语音识别引擎、模型、设备和语言保存后重新 Launch 生效。"
        )
        self.apply_hint.setWordWrap(True)
        self.apply_hint.setStyleSheet(
            "color: #f9e2af; background: rgba(255,255,255,10); "
            "border-radius: 7px; padding: 8px 10px;"
        )
        layout.addRow(self.apply_hint)
        self.asr_backend = ReadableComboBox()
        # Only show engines that are installed and tested in AnoTime's bundled
        # PySide runtime.  Legacy Whisper/FunASR code remains available for
        # developers who install those optional dependencies themselves, but a
        # normal user must never be able to select a backend that cannot start.
        self.available_backends = ("apple", "parakeet_eou", "mlx")
        self.asr_backend.addItems(self.available_backends)
        configured_backend = self.settings.asr_backend
        self.asr_backend.setCurrentText(
            configured_backend
            if configured_backend in self.available_backends
            else "apple"
        )
        self.asr_backend.setToolTip(
            "parakeet_eou: Experimental local English streaming CoreML model\n"
            "mlx: Apple Silicon MLX Whisper (local, higher latency)"
        )
        self.asr_backend.currentTextChanged.connect(self.on_backend_changed)
        layout.addRow("ASR Backend（语音识别引擎）:", self.asr_backend)

        self.backend_hint = QLabel()
        self.backend_hint.setWordWrap(True)
        self.backend_hint.setStyleSheet(
            "color: #a6e3a1; padding: 8px 10px; "
            "background: rgba(255, 255, 255, 12); border-radius: 7px;"
        )
        layout.addRow("", self.backend_hint)

        self.whisper_model = ReadableComboBox()
        self.whisper_model.addItems([
            "tiny", "tiny.en", "base", "base.en", "small", "small.en",
            "medium", "medium.en", "large-v3", "turbo",
        ])
        self.whisper_model.setCurrentText(self.settings.whisper_model)
        layout.addRow("Whisper Model（Whisper 模型大小）:", self.whisper_model)

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
            "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        ])
        self.funasr_model.setCurrentText(self.settings.funasr_model)
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
        self.device_type.setCurrentText(self.settings.whisper_device)
        self.device_type.currentTextChanged.connect(self.on_device_changed)
        layout.addRow("Compute Device（计算设备）:", self.device_type)

        self.compute_type = ReadableComboBox()
        self.compute_type.addItems(["int8", "float16", "float32"])
        self.compute_type.setCurrentText(self.settings.whisper_compute_type)
        self.compute_type.currentTextChanged.connect(self.on_quantization_changed)
        layout.addRow("Quantization（推理精度与内存占用）:", self.compute_type)

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
        source_lang = self.settings.source_language or "auto"
        source_index = self.source_language.findData(source_lang)
        if source_index >= 0:
            self.source_language.setCurrentIndex(source_index)
        else:
            self.source_language.setCurrentText(source_lang)
        layout.addRow("Source Language（原文语言）:", self.source_language)
        self.on_backend_changed(self.settings.asr_backend)

    def on_backend_changed(self, backend):
        is_whisper_or_mlx = backend in ("whisper", "mlx")
        is_funasr = backend == "funasr"
        is_parakeet = backend == "parakeet_eou"
        self.set_row_visible(self.whisper_model, is_whisper_or_mlx)
        self.set_row_visible(self.funasr_model, is_funasr)
        self.set_row_visible(self.device_type, backend in ("whisper", "funasr"))
        self.set_row_visible(self.compute_type, backend == "whisper")
        if is_parakeet:
            english_index = self.source_language.findData("en")
            if english_index >= 0:
                self.source_language.setCurrentIndex(english_index)
        self.source_language.setEnabled(not is_parakeet)
        hints = {
            "apple": "Apple 原生实时识别：只使用原文语言，其他模型参数已隐藏。",
            "parakeet_eou": (
                "Parakeet EOU（实验）：本地英文 CoreML 流式识别；首次需要下载约 "
                "500 MB 模型。本机首个英文通常更快，但 CPU/内存更高，长句收尾仍需观察；默认建议 Apple。"
            ),
            "mlx": "MLX Whisper：使用所选 Whisper 模型，并自动调用 Apple Silicon Metal。",
            "whisper": "Faster-Whisper：模型、计算设备和推理精度均会参与运行。",
            "funasr": "FunASR：使用所选模型和计算设备；MPS 会自动采用 float32。",
        }
        self.backend_hint.setText(hints.get(backend, ""))
        if is_funasr:
            self.check_funasr_mps_compatibility()

    def set_row_visible(self, field, visible):
        field.setVisible(visible)
        label = self.form_layout.labelForField(field)
        if label:
            label.setVisible(visible)

    def check_funasr_mps_compatibility(self):
        if self.device_type.currentText() != "mps":
            return
        if self.compute_type.currentText() == "float32":
            return
        self.show_mps_float32_warning()
        float32_index = self.compute_type.findText("float32")
        if float32_index >= 0:
            self.compute_type.setCurrentIndex(float32_index)

    def show_mps_float32_warning(self):
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Quantization Compatibility")
        message.setText("MPS device requires float32 quantization with FunASR")
        message.setInformativeText(
            "Apple's MPS (Metal Performance Shaders) does not support float64 operations.\n\n"
            "When using FunASR with MPS device, quantization must be set to 'float32'.\n\n"
            "The quantization has been automatically switched to float32."
        )
        message.setStandardButtons(QMessageBox.StandardButton.Ok)
        message.exec()

    def on_device_changed(self, _device):
        if self.asr_backend.currentText() == "funasr":
            self.check_funasr_mps_compatibility()

    def on_quantization_changed(self, _quantization):
        if self.asr_backend.currentText() == "funasr":
            self.check_funasr_mps_compatibility()
