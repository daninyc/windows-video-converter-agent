from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from media_converter.media.models import ConversionSettings
from media_converter.media.settings import (
    AUDIO_ENCODERS,
    DEFAULT_ENCODERS,
    VIDEO_ENCODERS,
    SettingsService,
)


class SettingsPanel(QWidget):
    settings_changed = Signal(object)
    validation_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settings_panel")
        self._loading = True
        self._current = ConversionSettings()
        self.service = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        heading = QLabel("整批输出参数")
        heading.setObjectName("section")
        layout.addWidget(heading)
        help_text = QLabel("更改用于下一批；转换中的参数已固定。")
        help_text.setWordWrap(True)
        help_text.setObjectName("muted")
        layout.addWidget(help_text)
        self.preset_layout = QHBoxLayout()
        layout.addLayout(self.preset_layout)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.container_combo = QComboBox()
        for value in DEFAULT_ENCODERS:
            self.container_combo.addItem(value.upper(), value)
        self.video_combo = QComboBox()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("恒定质量 CRF", "crf")
        self.mode_combo.addItem("固定码率", "bitrate")
        self.quality_edit = QLineEdit("23")
        self.video_bitrate_edit = QLineEdit()
        self.video_bitrate_edit.setPlaceholderText("bit/s，例如 2000000")
        self.resolution_combo = QComboBox()
        for caption, value in [
            ("保持原始", None),
            ("480p 范围", (854, 480)),
            ("720p 范围", (1280, 720)),
            ("1080p 范围", (1920, 1080)),
            ("4K 范围", (3840, 2160)),
            ("自定义范围", "custom"),
        ]:
            self.resolution_combo.addItem(caption, value)
        self.width_edit, self.height_edit = QLineEdit(), QLineEdit()
        resolution = QWidget()
        size_layout = QHBoxLayout(resolution)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.addWidget(self.width_edit)
        size_layout.addWidget(QLabel("×"))
        size_layout.addWidget(self.height_edit)
        self.frame_rate_edit = QLineEdit()
        self.frame_rate_edit.setPlaceholderText("保持原始；或 30、30000/1001")
        self.audio_combo = QComboBox()
        self.audio_bitrate_edit = QLineEdit()
        self.audio_bitrate_edit.setPlaceholderText("自动；或 bit/s")
        self.output_mode_combo = QComboBox()
        self.output_mode_combo.addItem("统一输出目录", "unified")
        self.output_mode_combo.addItem("源文件旁的转换结果", "beside_source")
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("请选择输出文件夹")
        self.output_button = QPushButton("选择输出目录")
        self.hierarchy_checkbox = QCheckBox("保留来源层级")
        for caption, widget in [
            ("格式", self.container_combo),
            ("视频编码", self.video_combo),
            ("模式", self.mode_combo),
            ("CRF", self.quality_edit),
            ("视频码率", self.video_bitrate_edit),
            ("尺寸", self.resolution_combo),
            ("宽 × 高", resolution),
            ("帧率", self.frame_rate_edit),
            ("音频", self.audio_combo),
            ("音频码率", self.audio_bitrate_edit),
            ("保存方式", self.output_mode_combo),
        ]:
            form.addRow(caption, widget)
        layout.addLayout(form)
        layout.addWidget(self.output_dir_edit)
        layout.addWidget(self.output_button)
        layout.addWidget(self.hierarchy_checkbox)
        self.validation_label = QLabel()
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #a13928;")
        layout.addWidget(self.validation_label)
        layout.addStretch()
        self.output_button.clicked.connect(self._choose_output)
        self.container_combo.currentIndexChanged.connect(self._container_changed)
        self.video_combo.currentIndexChanged.connect(self._encoder_changed)
        for combo in [
            self.mode_combo,
            self.resolution_combo,
            self.audio_combo,
            self.output_mode_combo,
        ]:
            combo.currentIndexChanged.connect(self._changed)
        for editor in [
            self.quality_edit,
            self.video_bitrate_edit,
            self.width_edit,
            self.height_edit,
            self.frame_rate_edit,
            self.audio_bitrate_edit,
            self.output_dir_edit,
        ]:
            editor.editingFinished.connect(self._changed)
        self.hierarchy_checkbox.toggled.connect(self._changed)
        self.set_settings(self._current)

    def set_capabilities(self, capabilities):
        self.service = SettingsService(capabilities)
        self._mark_available()
        self._changed()

    def _mark_available(self):
        if self.service is None:
            return
        for combo, kind in [(self.video_combo, "video"), (self.audio_combo, "audio")]:
            for index in range(combo.count()):
                value = combo.itemText(index) if kind == "video" else combo.itemData(index)
                combo.model().item(index).setEnabled(
                    value in ("auto", "copy") or value in self.service.capabilities.encoders
                )

    def _populate_encoders(self, container):
        self.video_combo.clear()
        self.video_combo.addItems(VIDEO_ENCODERS[container])
        self.audio_combo.clear()
        for value in AUDIO_ENCODERS[container]:
            caption = {"auto": "自动（兼容时复制）", "copy": "仅复制"}.get(value, value)
            self.audio_combo.addItem(caption, value)
        self._mark_available()

    def _container_changed(self):
        if self._loading:
            return
        self._loading = True
        container = self.container_combo.currentData()
        self._populate_encoders(container)
        video, audio, quality = DEFAULT_ENCODERS[container]
        self.video_combo.setCurrentText(video)
        self.audio_combo.setCurrentIndex(self.audio_combo.findData(audio))
        self.quality_edit.setText(str(quality))
        self._loading = False
        self._changed()

    def _encoder_changed(self):
        if not self._loading:
            self.quality_edit.setText(
                "32" if self.video_combo.currentText() == "libvpx-vp9" else "23"
            )
            self._changed()

    def _choose_output(self):
        directory = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if directory:
            self.output_dir_edit.setText(directory)
            self._changed()

    def _read(self):
        selected = self.resolution_combo.currentData()
        resolution = None
        if selected == "custom":
            resolution = {"width": self.width_edit.text(), "height": self.height_edit.text()}
        elif selected:
            resolution = {"width": selected[0], "height": selected[1]}
        frame_rate = None
        if self.frame_rate_edit.text().strip():
            try:
                fraction = Fraction(self.frame_rate_edit.text().strip())
                frame_rate = {"numerator": fraction.numerator, "denominator": fraction.denominator}
            except (ValueError, ZeroDivisionError):
                frame_rate = {"numerator": 0, "denominator": 0}
        unified = self.output_mode_combo.currentData() == "unified"
        crf = self.mode_combo.currentData() == "crf"
        return {
            "settings_version": self._current.settings_version,
            "container": self.container_combo.currentData(),
            "video_encoder": self.video_combo.currentText(),
            "quality_mode": self.mode_combo.currentData(),
            "quality_value": self.quality_edit.text() if crf else None,
            "video_bitrate_bps": self.video_bitrate_edit.text() if not crf else None,
            "resolution": resolution,
            "frame_rate": frame_rate,
            "audio_encoder": self.audio_combo.currentData(),
            "audio_bitrate_bps": self.audio_bitrate_edit.text().strip() or None,
            "output_mode": self.output_mode_combo.currentData(),
            "output_dir": Path(self.output_dir_edit.text().strip())
            if self.output_dir_edit.text().strip()
            else None,
            "preserve_hierarchy": unified and self.hierarchy_checkbox.isChecked(),
        }

    def validation(self, *, require_output=False):
        return (
            self.service.validate(self._read(), require_output=require_output)
            if self.service
            else None
        )

    def _changed(self):
        if self._loading:
            return
        crf = self.mode_combo.currentData() == "crf"
        unified = self.output_mode_combo.currentData() == "unified"
        custom = self.resolution_combo.currentData() == "custom"
        self.quality_edit.setEnabled(crf)
        self.video_bitrate_edit.setEnabled(not crf)
        self.width_edit.setEnabled(custom)
        self.height_edit.setEnabled(custom)
        self.output_dir_edit.setEnabled(unified)
        self.output_button.setEnabled(unified)
        self.hierarchy_checkbox.setEnabled(unified)
        validation = self.validation()
        if validation:
            self.validation_label.setText("；".join(issue.message for issue in validation.issues))
            if validation.valid:
                result = self.service.update(self._current, validation.settings.model_dump())
                self._current = result.settings
                self.settings_changed.emit(self._current)
        self.validation_changed.emit()

    def set_settings(self, settings):
        self._loading = True
        self._current = settings
        self.container_combo.setCurrentIndex(self.container_combo.findData(settings.container))
        self._populate_encoders(settings.container)
        if self.video_combo.findText(settings.video_encoder) < 0:
            self.video_combo.addItem(settings.video_encoder)
        self.video_combo.setCurrentText(settings.video_encoder)
        if self.audio_combo.findData(settings.audio_encoder) < 0:
            self.audio_combo.addItem(settings.audio_encoder, settings.audio_encoder)
        self.audio_combo.setCurrentIndex(self.audio_combo.findData(settings.audio_encoder))
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(settings.quality_mode))
        self.quality_edit.setText(
            str(settings.quality_value) if settings.quality_value is not None else ""
        )
        self.video_bitrate_edit.setText(
            str(settings.video_bitrate_bps) if settings.video_bitrate_bps else ""
        )
        self.resolution_combo.setCurrentIndex(
            self.resolution_combo.count() - 1 if settings.resolution else 0
        )
        self.width_edit.setText(str(settings.resolution.width) if settings.resolution else "")
        self.height_edit.setText(str(settings.resolution.height) if settings.resolution else "")
        rate = settings.frame_rate
        self.frame_rate_edit.setText(f"{rate.numerator}/{rate.denominator}" if rate else "")
        self.audio_bitrate_edit.setText(
            str(settings.audio_bitrate_bps) if settings.audio_bitrate_bps else ""
        )
        self.output_mode_combo.setCurrentIndex(
            self.output_mode_combo.findData(settings.output_mode)
        )
        self.output_dir_edit.setText(str(settings.output_dir) if settings.output_dir else "")
        self.hierarchy_checkbox.setChecked(settings.preserve_hierarchy)
        self._loading = False
        self._changed()
