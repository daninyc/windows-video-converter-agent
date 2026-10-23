from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


class AgentPanel(QWidget):
    send_requested = Signal(str)
    stop_requested = Signal()
    retry_requested = Signal()
    new_requested = Signal()
    conversation_selected = Signal(str)
    reference_video = Signal()
    reference_task = Signal()
    reference_file = Signal()
    revoke_requested = Signal()
    api_requested = Signal()
    proposal_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        row = QHBoxLayout()
        self.conversations = QComboBox()
        self.conversations.setAccessibleName("AI 会话")
        self.new_button = QPushButton("新建")
        self.api_button = QPushButton("接入设置")
        row.addWidget(self.conversations, 1)
        row.addWidget(self.new_button)
        row.addWidget(self.api_button)
        layout.addLayout(row)
        self.reference_toggle = QPushButton("引用素材（0） · 展开管理")
        layout.addWidget(self.reference_toggle)
        reference_box = QWidget()
        reference_layout = QVBoxLayout(reference_box)
        reference_layout.setContentsMargins(0, 0, 0, 0)
        reference_layout.addWidget(QLabel("当前明确引用（发送时固定）"))
        self.references = QListWidget()
        self.references.setMaximumHeight(48)
        reference_layout.addWidget(self.references)
        refrow = QGridLayout()
        self.video_button = QPushButton("引用视频")
        self.task_button = QPushButton("引用任务")
        self.file_button = QPushButton("引用文档")
        self.revoke_button = QPushButton("撤销引用")
        for i, button in enumerate(
            (self.video_button, self.task_button, self.file_button, self.revoke_button)
        ):
            refrow.addWidget(button, i // 2, i % 2)
        reference_layout.addLayout(refrow)
        reference_box.hide()
        self.reference_toggle.clicked.connect(
            lambda: reference_box.setVisible(not reference_box.isVisible())
        )
        layout.addWidget(reference_box)
        self.messages = QTextBrowser()
        self.messages.setAccessibleName("AI 聊天历史")
        self.messages.setOpenExternalLinks(False)
        self.messages.setOpenLinks(False)
        self.messages.setMinimumHeight(100)
        layout.addWidget(self.messages, 1)
        self.status = QLabel("可查询和建议参数；实际在线问答需要配置接入。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.trace = QLabel("诊断标识：发送问题后显示")
        self.trace.setWordWrap(True)
        self.trace.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.trace)
        self.tool_details = QTextBrowser()
        self.tool_details.setAccessibleName("本会话工具摘要和诊断标识")
        self.tool_details.setMaximumHeight(80)
        self.tool_details.hide()
        details_button = QPushButton("查看 / 收起工具摘要")
        details_button.clicked.connect(
            lambda: self.tool_details.setVisible(not self.tool_details.isVisible())
        )
        layout.addWidget(details_button)
        layout.addWidget(self.tool_details)
        self.sources = QListWidget()
        self.sources.setMaximumHeight(48)
        self.sources.hide()
        self.sources.setAccessibleName("回答来源，双击定位")
        layout.addWidget(self.sources)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("输入问题；文档需先明确引用")
        self.input.setFixedHeight(68)
        self.input.setTabChangesFocus(True)
        self.input.setAccessibleName("AI 问题输入框")
        layout.addWidget(self.input)
        actions = QGridLayout()
        self.send_button = QPushButton("发送")
        self.stop_button = QPushButton("停止回答")
        self.retry_button = QPushButton("重试本轮")
        self.proposal_button = QPushButton("查看参数建议")
        self.proposal_button.setEnabled(False)
        for i, button in enumerate(
            (self.send_button, self.stop_button, self.retry_button, self.proposal_button)
        ):
            actions.addWidget(button, i // 2, i % 2)
        layout.addLayout(actions)
        self.send_button.clicked.connect(self.send)
        self.stop_button.clicked.connect(self.stop_requested)
        self.retry_button.clicked.connect(self.retry_requested)
        self.new_button.clicked.connect(self.new_requested)
        self.api_button.clicked.connect(self.api_requested)
        self.video_button.clicked.connect(self.reference_video)
        self.task_button.clicked.connect(self.reference_task)
        self.file_button.clicked.connect(self.reference_file)
        self.revoke_button.clicked.connect(self.revoke_requested)
        self.proposal_button.clicked.connect(self.proposal_requested)
        self.conversations.currentIndexChanged.connect(
            lambda: self.conversation_selected.emit(self.conversations.currentData() or "")
        )

    def send(self):
        text = self.input.toPlainText().strip()
        if text:
            self.send_requested.emit(text)

    def set_conversations(self, values, current_id):
        self.conversations.blockSignals(True)
        self.conversations.clear()
        for value in values:
            self.conversations.addItem(value.title, value.conversation_id)
        self.conversations.setCurrentIndex(self.conversations.findData(current_id))
        self.conversations.blockSignals(False)
