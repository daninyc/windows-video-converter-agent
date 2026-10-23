from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtWidgets import QFileDialog

from media_converter.media.importer import VIDEO_EXTENSIONS


class ImportActions(QObject):
    paths_requested = Signal(object, bool)

    def __init__(self, window, recursive_checkbox):
        super().__init__(window)
        self.window = window
        self.recursive_checkbox = recursive_checkbox
        window.setAcceptDrops(True)
        window.installEventFilter(self)
        window.add_files_button.clicked.connect(self.choose_files)
        window.add_folder_button.clicked.connect(self.choose_directory)

    def request(self, paths):
        if paths:
            self.paths_requested.emit(
                tuple(Path(path) for path in paths), self.recursive_checkbox.isChecked()
            )

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self.window,
            "添加视频",
            "",
            "视频 (" + " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS)) + ");;所有文件 (*)",
        )
        self.request(files)

    def choose_directory(self):
        directory = QFileDialog.getExistingDirectory(self.window, "添加视频文件夹")
        self.request([directory] if directory else [])

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.Drop) and event.mimeData().hasUrls():
            local = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if local:
                event.acceptProposedAction()
                if event.type() == QEvent.Type.Drop:
                    self.request(local)
                return True
        return super().eventFilter(watched, event)
