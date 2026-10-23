import json

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
)

FIELD_LABELS = {
    "container": "目标格式",
    "video_encoder": "视频编码",
    "quality_mode": "质量模式",
    "quality_value": "恒定质量 CRF",
    "video_bitrate_bps": "视频码率（bit/s）",
    "resolution": "尺寸范围",
    "frame_rate": "帧率",
    "audio_encoder": "音频编码",
    "audio_bitrate_bps": "音频码率（bit/s）",
}


def display_value(key, value):
    if value is None:
        return "自动 / 保持原始"
    if key == "quality_mode":
        return {"crf": "恒定质量 CRF", "bitrate": "固定码率"}.get(value, str(value))
    if key == "resolution":
        return f"{value['width']} × {value['height']}"
    if key == "frame_rate":
        return f"{value['numerator']} / {value['denominator']} fps"
    return str(value)


class SettingsDiffDialog(QDialog):
    def __init__(self, proposal, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认下一批转换参数")
        self.resize(580, 440)
        layout = QVBoxLayout(self)
        self.preview = QTextBrowser()
        old = current.model_dump(mode="json")
        patch = json.loads(proposal.patch_json)
        lines = ["仅影响下一批；已在运行的计划使用原快照。", "", "修改内容："]
        lines.extend(
            f"{FIELD_LABELS.get(key, key)}：{display_value(key, old.get(key))} → "
            f"{display_value(key, value)}"
            for key, value in patch.items()
        )
        lines.extend(["", "理由：", proposal.reason, "", "来源："])
        for source in json.loads(proposal.sources_json):
            title = source.get("title") or source.get("section_id") or "本轮明确引用的资料"
            location = source.get("url") or source.get("location")
            lines.append(str(title) + (f"（{location}）" if location else ""))
        self.preview.setPlainText("\n".join(lines))
        layout.addWidget(self.preview)
        self.note = QLabel("应用后仍需手动开始转换；轨道丢失确认仍按实际转换计划执行。")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.confirm = QCheckBox("我已核对修改、理由和来源，同意应用到下一批参数")
        layout.addWidget(self.confirm)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText("应用到下一批")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.apply_button.setEnabled(False)
        self.confirm.toggled.connect(self.apply_button.setEnabled)
        self.apply_button.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
