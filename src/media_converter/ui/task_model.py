from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QIcon

from media_converter.jobs.models import JobState

STATE_LABELS = {
    "pending": "等待读取",
    "probing": "读取信息中",
    "succeeded": "就绪",
    "failed": "读取失败",
    JobState.QUEUED: "等待转换",
    JobState.PREPARING: "准备中",
    JobState.NEEDS_CONFIRMATION: "需要确认",
    JobState.READY: "等待执行",
    JobState.RUNNING: "转换中",
    JobState.VERIFYING: "验证输出",
    JobState.CANCELLING: "正在取消",
    JobState.CANCELLED: "已取消",
    JobState.FAILED: "转换失败",
    JobState.SUCCEEDED: "转换成功",
    JobState.INTERRUPTED: "上次运行已中断",
}


@dataclass
class TaskRow:
    asset: object
    attempt: object = None
    icon: object = None


def format_duration(microseconds):
    if microseconds is None:
        return "未知"
    seconds = microseconds / 1_000_000
    if seconds < 1:
        return f"{seconds:.3f} 秒"
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


class TaskModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return ["文件", "状态", "时长", "输出 / 格式"][section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        row = self.rows[index.row()]
        asset, attempt = row.asset, row.attempt
        state = attempt.state if attempt else asset.probe_status
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                asset.resolved_path.name,
                STATE_LABELS.get(state, state),
                format_duration(asset.duration_us),
                (
                    Path(attempt.output_path).name
                    if attempt and attempt.output_path
                    else asset.container or "未知"
                ),
            ][index.column()]
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            return row.icon
        if role == Qt.ItemDataRole.UserRole:
            return asset.asset_id
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(asset.resolved_path) + (
                "\n" + attempt.output_path if attempt and attempt.output_path else ""
            )
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return QColor(
                "#a13928"
                if state in ("failed", JobState.FAILED)
                else "#24604c"
                if state == JobState.SUCCEEDED
                else "#42556e"
            )

    def find(self, asset_id):
        return next(
            (index for index, row in enumerate(self.rows) if row.asset.asset_id == asset_id), None
        )

    def add(self, asset):
        if self.find(asset.asset_id) is not None:
            self.update_asset(asset)
            return
        row = len(self.rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self.rows.append(TaskRow(asset))
        self.endInsertRows()

    def changed(self, row):
        self.dataChanged.emit(self.index(row, 0), self.index(row, 3))

    def update_asset(self, asset):
        index = self.find(asset.asset_id)
        if index is not None:
            self.rows[index].asset = asset
            self.changed(index)

    def set_attempt(self, attempt):
        index = self.find(attempt.asset_id)
        if index is not None:
            self.rows[index].attempt = attempt
            self.changed(index)

    def set_thumbnail(self, asset, result):
        index = self.find(asset.asset_id)
        if index is not None and self.rows[index].asset.fingerprint == asset.fingerprint:
            self.rows[index].icon = QIcon(str(result.path)) if result.path else QIcon()
            self.changed(index)

    def remove(self, asset_id):
        index = self.find(asset_id)
        if index is not None:
            self.beginRemoveRows(QModelIndex(), index, index)
            self.rows.pop(index)
            self.endRemoveRows()
