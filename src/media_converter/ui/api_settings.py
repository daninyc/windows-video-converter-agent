from pydantic import ValidationError
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from media_converter.common.errors import AppError
from media_converter.services.config import APIConfig


class APISettingsDialog(QDialog):
    def __init__(self, service, parent=None, on_test=None):
        super().__init__(parent)
        self.service, self.on_test = service, on_test
        self.setWindowTitle("AI 接入设置")
        self.resize(520, 300)
        self.config = service.load()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.url_edit = QLineEdit(self.config.base_url)
        self.model_edit = QLineEdit(self.config.model)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText(
            "已保存凭据；留空保留" if self.config.credential_ref else "尚未配置"
        )
        form.addRow("API 地址", self.url_edit)
        form.addRow("模型", self.model_edit)
        form.addRow("API Key", self.key_edit)
        layout.addLayout(form)
        note = QLabel(
            "凭据仅供当前 Windows 用户使用。接入有效期由提供方控制，"
            "应用不自动延长或保证一小时失效。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.clear_button = QPushButton("清除已保存凭据")
        self.clear_button.clicked.connect(self.clear)
        layout.addWidget(self.clear_button)
        self.test_button = QPushButton("测试已保存的连接")
        self.test_button.setEnabled(on_test is not None)
        self.test_button.clicked.connect(lambda: self.on_test(self.status))
        layout.addWidget(self.test_button)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def save(self):
        try:
            config = APIConfig(
                base_url=self.url_edit.text(),
                model=self.model_edit.text(),
                timeout_seconds=self.config.timeout_seconds,
            )
            self.config = self.service.save(config, self.key_edit.text() or None)
            self.key_edit.clear()
            self.accept()
        except (ValidationError, AppError, OSError):
            self.status.setText("无法保存，请检查 API 地址、模型和私密目录权限。")

    def clear(self):
        try:
            self.config = self.service.save(self.config, clear=True)
            self.key_edit.clear()
            self.key_edit.setPlaceholderText("凭据已清除")
            self.status.setText("已清除；新的在线请求需要重新配置。")
        except (AppError, OSError):
            self.status.setText("无法清除，请检查私密目录权限。")
