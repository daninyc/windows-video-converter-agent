import json
from datetime import datetime

from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QPushButton, QTextBrowser, QVBoxLayout

from media_converter.services.diagnostics import Diagnostics


def show_diagnostics(window):
    dialog = QDialog(window)
    dialog.setWindowTitle("本地诊断")
    dialog.resize(620, 440)
    layout = QVBoxLayout(dialog)
    info = QLabel("只导出版本、工具状态和匿名标识；不包含密钥、数据库、文档原文或视频。")
    info.setWordWrap(True)
    layout.addWidget(info)
    browser = QTextBrowser()
    browser.setAccessibleName("诊断摘要")
    layout.addWidget(browser)
    service = Diagnostics(window.paths.data_dir)
    context, records = service.collect()
    browser.setPlainText(
        json.dumps({**context, "recent_events": records[-10:]}, ensure_ascii=False, indent=2)
    )
    status = QLabel("诊断仅保存在你选择的位置，不会上传。")
    status.setWordWrap(True)
    layout.addWidget(status)
    export = QPushButton("导出诊断 ZIP")
    layout.addWidget(export)

    def save():
        name = "diagnostics-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip"
        path, _ = QFileDialog.getSaveFileName(
            dialog, "保存诊断", str(window.paths.data_dir / name), "诊断归档 (*.zip)"
        )
        if path:
            try:
                result = service.export(path)
                status.setText(f"已导出 {result['records']} 条脱敏记录。")
            except OSError:
                status.setText("导出失败；请选择可写目录和新的文件名。")

    export.clicked.connect(save)
    close = QPushButton("关闭")
    close.clicked.connect(dialog.close)
    layout.addWidget(close)
    dialog.exec()
