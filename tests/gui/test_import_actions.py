import pytest
from PySide6.QtWidgets import QCheckBox, QFileDialog

from media_converter.config import AppPaths
from media_converter.ui.import_actions import ImportActions
from media_converter.ui.main_window import MainWindow

pytestmark = pytest.mark.gui


def test_file_folder_and_drop_share_request(qtbot, tmp_path, monkeypatch):
    window = MainWindow(AppPaths.from_argument(tmp_path))
    qtbot.addWidget(window)
    recursive = QCheckBox(window)
    actions = ImportActions(window, recursive)
    received = []
    actions.paths_requested.connect(lambda paths, deep: received.append((paths, deep)))
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", lambda *a: ([str(tmp_path / "中文.mp4")], "")
    )
    actions.choose_files()
    assert received[-1][1] is False
    recursive.setChecked(True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(tmp_path))
    actions.choose_directory()
    assert received[-1] == ((tmp_path,), True)
    actions.request([tmp_path / "drop.mp4"])
    assert received[-1][0][0].name == "drop.mp4"


def test_real_drop_event_accepts_only_local_urls(qtbot, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication

    window = MainWindow(AppPaths.from_argument(tmp_path))
    qtbot.addWidget(window)
    actions = ImportActions(window, QCheckBox(window))
    received = []
    actions.paths_requested.connect(lambda paths, recursive: received.extend(paths))
    mime = QMimeData()
    mime.setUrls(
        [QUrl.fromLocalFile(str(tmp_path / "拖入.mp4")), QUrl("https://example.com/video.mp4")]
    )
    enter = QDragEnterEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(window, enter)
    assert enter.isAccepted()
    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(window, drop)
    assert received == [tmp_path / "拖入.mp4"]
