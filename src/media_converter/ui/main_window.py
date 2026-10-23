from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from media_converter.config import AppPaths
from media_converter.ui.settings_panel import SettingsPanel
from media_converter.ui.task_model import TaskModel


def label(text, style=None, *, wrap=False):
    widget = QLabel(text)
    if style:
        widget.setObjectName(style)
    widget.setWordWrap(wrap)
    return widget


def panel():
    widget = QFrame()
    widget.setObjectName("panel")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)
    return widget, layout


def unavailable_button(text, reason):
    button = QPushButton(text)
    button.setEnabled(False)
    button.setToolTip(reason)
    button.setAccessibleDescription(reason)
    return button


class MainWindow(QMainWindow):
    closing = Signal()

    def __init__(self, paths: AppPaths):
        super().__init__()
        self.paths = paths
        self.setWindowTitle("视频转换器")
        self.setMinimumSize(1080, 600)
        self.resize(1400, 900)
        diagnostics = self.menuBar().addMenu("帮助").addAction("查看 / 导出本地诊断")
        from media_converter.ui.diagnostics_dialog import show_diagnostics

        diagnostics.triggered.connect(lambda: show_diagnostics(self))
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 20, 14, 14)
        outer.setSpacing(12)
        header = QHBoxLayout()
        title = QVBoxLayout()
        title.addWidget(label("视频转换器", "heading"))
        title.addWidget(label("导入、查看信息、设置参数，然后顺序转换。", "muted"))
        header.addLayout(title)
        header.addStretch()
        header.addWidget(label("本地转换", "badge"))
        outer.addLayout(header)
        actions = QHBoxLayout()
        self.add_files_button = unavailable_button("添加文件", "正在准备视频组件")
        self.add_folder_button = unavailable_button("添加文件夹", "正在准备视频组件")
        self.recursive_checkbox = QCheckBox("扫描子文件夹")
        self.ai_toggle = QPushButton("AI 助手  Alt+A")
        self.setup_button = QPushButton("准备 AI")
        self.setup_button.setAccessibleName("检查和准备 AI 组件")
        self.ai_toggle.setShortcut("Alt+A")
        self.ai_toggle.setAccessibleName("显示或隐藏 AI 助手")
        for widget in [self.add_files_button, self.add_folder_button, self.recursive_checkbox]:
            actions.addWidget(widget)
        actions.addStretch()
        actions.addWidget(self.setup_button)
        actions.addWidget(self.ai_toggle)
        outer.addLayout(actions)
        self.notice_label = label("请选择视频；正在检查本机视频组件。", "muted", wrap=True)
        outer.addWidget(self.notice_label)
        self.import_report = QTextBrowser()
        self.import_report.setMaximumHeight(90)
        self.import_report.hide()
        outer.addWidget(self.import_report)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)
        tasks, task_layout = panel()
        tasks.setMinimumWidth(360)
        task_layout.addWidget(label("转换任务", "section"))
        self.task_model = TaskModel(self)
        self.task_table = QTableView()
        self.task_table.setModel(self.task_model)
        self.task_table.setMinimumHeight(130)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_table.setIconSize(QSize(96, 54))
        self.task_table.verticalHeader().hide()
        self.task_table.verticalHeader().setDefaultSectionSize(66)
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.task_table.setColumnWidth(2, 70)
        self.task_table.setColumnWidth(3, 110)
        self.task_table.setAccessibleName("转换任务列表")
        task_layout.addWidget(self.task_table, 1)
        self.empty_label = label(
            "还没有视频任务\n添加文件、文件夹或将本地视频拖入窗口。", "emptyTitle", wrap=True
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(64)
        task_layout.addWidget(self.empty_label)
        item_actions = QHBoxLayout()
        self.remove_button = unavailable_button("移除", "先选择素材，移除不会删除源文件")
        self.refresh_button = unavailable_button("重新读取", "先选择需要重新读取的信息")
        self.retry_button = unavailable_button("重试转换", "选择失败、取消或中断的任务")
        self.open_button = unavailable_button("打开结果位置", "选择已有输出的任务")
        for widget in [
            self.remove_button,
            self.refresh_button,
            self.retry_button,
            self.open_button,
        ]:
            item_actions.addWidget(widget)
        task_layout.addLayout(item_actions)
        task_layout.addWidget(label("视频详情", "section"))
        self.details_panel = QTextBrowser()
        self.details_panel.setMinimumHeight(110)
        self.details_panel.setMaximumHeight(190)
        self.details_panel.setPlainText("选择视频后查看容器、尺寸、音轨、字幕和输出信息。")
        task_layout.addWidget(self.details_panel)
        task_scroll = QScrollArea()
        task_scroll.setFrameShape(QFrame.Shape.NoFrame)
        task_scroll.setWidgetResizable(True)
        task_scroll.setWidget(tasks)
        task_scroll.setMinimumWidth(440)
        splitter.addWidget(task_scroll)
        self.settings_panel = SettingsPanel()
        self.settings_panel.setEnabled(False)
        self.container_combo = self.settings_panel.container_combo
        settings_scroll = QScrollArea()
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setMinimumWidth(300)
        settings_scroll.setWidget(self.settings_panel)
        splitter.addWidget(settings_scroll)
        splitter.setSizes([650, 330])
        footer, footer_layout = panel()
        self.progress_label = label("0 个任务 · 等待导入", "muted")
        footer_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        footer_layout.addWidget(self.progress_bar)
        buttons = QHBoxLayout()
        buttons.addWidget(label("一次处理一个视频", "muted"))
        buttons.addStretch()
        self.cancel_button = unavailable_button("取消当前", "当前没有运行中的转换")
        self.cancel_batch_button = unavailable_button("取消整批", "当前没有运行中的批次")
        self.start_button = unavailable_button("开始转换", "先导入可转换的视频并选择输出位置")
        self.start_button.setObjectName("primary")
        for widget in [self.cancel_button, self.cancel_batch_button, self.start_button]:
            buttons.addWidget(widget)
        footer_layout.addLayout(buttons)
        outer.addWidget(footer)
        self.agent_dock = QDockWidget("AI 助手", self)
        self.agent_dock.setObjectName("agent_dock")
        self.agent_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.agent_dock.setMinimumWidth(250)
        self.agent_dock.setMaximumWidth(400)
        agent, agent_layout = panel()
        self.float_button = QPushButton("展开为独立窗口")
        self.float_button.setAccessibleName("切换 AI 助手停靠状态")
        self.float_button.clicked.connect(self._toggle_floating)
        agent_layout.addWidget(self.float_button)
        agent_layout.addSpacing(20)
        agent_layout.addWidget(label("让参数选择有依据", "section"))
        agent_layout.addWidget(
            label("AI 助手尚未启用。视频转换可直接使用，无需连接 AI 服务。", "muted", wrap=True)
        )
        agent_layout.addStretch()
        self.agent_dock.setWidget(agent)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.agent_dock)
        self.ai_toggle.clicked.connect(
            lambda: self.agent_dock.setVisible(not self.agent_dock.isVisible())
        )
        self.agent_dock.topLevelChanged.connect(
            lambda floating: self.float_button.setText(
                "收回到主窗口" if floating else "展开为独立窗口"
            )
        )
        QWidget.setTabOrder(self.add_files_button, self.add_folder_button)
        QWidget.setTabOrder(self.add_folder_button, self.recursive_checkbox)
        QWidget.setTabOrder(self.recursive_checkbox, self.task_table)

    def _toggle_floating(self):
        self.agent_dock.setFloating(not self.agent_dock.isFloating())

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_positioned", False):
            self._positioned = True
            available = self.screen().availableGeometry()
            self.resize(
                min(self.width(), available.width() - 24),
                min(self.height(), available.height() - 70),
            )
            self.move(available.x() + 12, available.y() + 30)

    def closeEvent(self, event):
        self.closing.emit()
        super().closeEvent(event)
