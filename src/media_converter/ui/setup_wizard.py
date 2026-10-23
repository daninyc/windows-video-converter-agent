import html

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from media_converter.services.preparer import SetupService

LABELS = {
    "video": "视频转换",
    "mcp": "查询工具",
    "knowledge": "知识检索与重排",
    "mysql": "结构化查询",
    "files": "授权文档读取",
    "environment": "运行环境",
    "services": "本地服务",
    "models": "文本模型",
    "ai-worker": "AI 运行组件",
}
STATES = {
    "checking": "检查中",
    "downloading": "下载中",
    "verifying": "校验中",
    "installing": "安装中",
    "reused": "已复用",
    "starting": "启动中",
    "warming": "预热中",
    "indexing": "构建索引",
    "missing": "缺少组件",
    "blocked": "需要处理",
}


class SetupWizard(QDialog):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("准备 AI 助手")
        self.resize(640, 570)
        self.setMinimumSize(460, 420)
        layout = QVBoxLayout(self)
        intro = QLabel("视频转换可以直接使用。此处准备本地查询能力；在线问答需另行配置接入。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.summary = QLabel("先检查现有组件，再选择复用或准备私有组件。")
        self.summary.setWordWrap(True)
        self.summary.setAccessibleName("AI 准备状态")
        layout.addWidget(self.summary)
        self.mode = QComboBox()
        self.mode.addItem("复用已配置的本地组件（推荐）", "reuse")
        self.mode.addItem("在当前数据目录准备私有组件", "private")
        self.mode.setAccessibleName("组件准备方式")
        layout.addWidget(self.mode)
        self.space = QLabel(
            f"完整组件下载约 {plan['download_bytes'] / 1024**3:.1f} GiB；"
            f"准备空间约 {plan['space_bytes'] / 1024**3:.1f} GiB；"
            f"当前可用 {plan['free_bytes'] / 1024**3:.1f} GiB。\n已有组件优先复用。"
        )
        self.space.setWordWrap(True)
        layout.addWidget(self.space)
        self.sources = QTextBrowser()
        self.sources.setAccessibleName("组件来源、版本与许可")
        self.sources.setMaximumHeight(105)
        self.sources.setHtml(
            "<br>".join(
                f"{html.escape(a['name'])} · {html.escape(a['version'][:16])} · "
                f"{html.escape(a['license'])}<br>{html.escape(a['source'])}"
                for a in plan.get("artifacts", [])
            )
        )
        layout.addWidget(self.sources)
        self.checks = QTreeWidget()
        self.checks.setHeaderLabels(["能力 / 组件", "状态", "说明"])
        self.checks.setRootIsDecorated(False)
        self.checks.setAccessibleName("组件检查和准备进度")
        layout.addWidget(self.checks, 1)
        self.rows = {}
        for name in ("video", "mcp", "knowledge", "mysql", "files"):
            self.update_event({"component": name, "state": "pending"})
        row = QHBoxLayout()
        self.inspect_button = QPushButton("重新检查")
        self.prepare_button = QPushButton("按所选方式准备")
        self.prepare_button.setEnabled(False)
        self.cancel_button = QPushButton("取消准备")
        self.cancel_button.setEnabled(False)
        for button in (self.inspect_button, self.prepare_button, self.cancel_button):
            row.addWidget(button)
        layout.addLayout(row)
        footer = QHBoxLayout()
        self.api_button = QPushButton("配置接入 / 测试连接")
        self.close_button = QPushButton("关闭此页")
        self.close_button.setToolTip("关闭页面后准备继续；取消请使用“取消准备”。")
        self.close_button.clicked.connect(self.close)
        footer.addWidget(self.api_button)
        footer.addStretch()
        footer.addWidget(self.close_button)
        layout.addLayout(footer)

    def update_event(self, event):
        name = event["component"]
        item = self.rows.get(name)
        if item is None:
            item = QTreeWidgetItem(self.checks, [LABELS.get(name, name), "", ""])
            self.rows[name] = item
        if "ok" in event:
            state = "可用" if event["ok"] else "需要处理"
        else:
            state = STATES.get(event.get("state"), "等待检查")
        if event.get("total"):
            state += f" {event['bytes'] * 100 / event['total']:.0f}%"
        item.setText(1, state)
        item.setText(2, "；".join(filter(None, (event.get("message"), event.get("action")))))
        item.setToolTip(2, item.text(2))
        self.checks.resizeColumnToContents(0)
        self.checks.resizeColumnToContents(1)

    def busy(self, value):
        self.inspect_button.setEnabled(not value)
        self.prepare_button.setEnabled(not value)
        self.mode.setEnabled(not value)
        self.cancel_button.setEnabled(value)


class SetupController(QObject):
    progress = Signal(object)

    def __init__(self, window, bridge, *, service=None, api_settings=lambda: None):
        super().__init__(window)
        self.window, self.bridge = window, bridge
        self.service = service or SetupService(window.paths.data_dir)
        self.dialog = None
        self.pending = None
        self.checked = False
        self.last_message = ""
        self.api_settings = api_settings
        self.progress.connect(self.update_event, Qt.ConnectionType.QueuedConnection)
        bridge.event_received.connect(self.finished)
        window.setup_button.clicked.connect(self.open)

    def open(self):
        if self.dialog is None:
            self.dialog = SetupWizard(self.service.plan(), self.window)
            if (self.window.paths.data_dir / "private-components.json").exists():
                self.dialog.mode.setCurrentIndex(1)
            self.dialog.inspect_button.clicked.connect(lambda: self.run(False))
            self.dialog.prepare_button.clicked.connect(lambda: self.run(True))
            self.dialog.cancel_button.clicked.connect(self.cancel)
            self.dialog.api_button.clicked.connect(self.api_settings)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        self.dialog.busy(bool(self.pending))
        if self.last_message:
            self.dialog.summary.setText(self.last_message)
        if not self.checked and not self.pending:
            self.run(False)

    def run(self, prepare):
        if self.pending:
            return
        self.dialog.busy(True)
        self.last_message = (
            "正在准备，可取消；关闭此页后会继续。" if prepare else "正在检查本地能力……"
        )
        self.dialog.summary.setText(self.last_message)
        mode = self.dialog.mode.currentData()
        self.pending = self.bridge.submit(
            lambda: (
                self.service.prepare(mode=mode, emit=self.progress.emit)
                if prepare
                else self.service.inspect(emit=self.progress.emit)
            )
        )

    def update_event(self, event):
        if self.dialog:
            self.dialog.update_event(event)

    def finished(self, event):
        if event.task_id != self.pending:
            return
        self.pending, self.checked = None, True
        if event.state == "succeeded":
            self.last_message = (
                "本地 AI 已就绪；在线问答请配置接入。"
                if event.data["ok"]
                else ("部分能力尚未就绪。查看下方原因，选择复用或准备私有组件；视频转换仍可使用。")
            )
        elif event.state == "cancelled":
            self.last_message = "准备已取消；已校验组件保留，下次可继续。"
        else:
            self.last_message = (
                event.error.message
                + "；"
                + event.error.suggested_action
                + "。处理后可重新准备，视频转换仍可使用。"
            )
        if self.dialog:
            self.dialog.summary.setText(self.last_message)
            self.dialog.busy(False)

    def cancel(self):
        async def request():
            self.service.cancel()

        self.bridge.submit(request)
        self.dialog.summary.setText("正在取消并清理所属资源……")
        self.dialog.cancel_button.setEnabled(False)

    async def shutdown(self):
        await self.service.close()
