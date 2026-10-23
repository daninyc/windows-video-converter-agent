from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QComboBox, QInputDialog, QPushButton


class PresetActions(QObject):
    save_requested = Signal(str)
    load_requested = Signal(str)

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.combo = QComboBox()
        self.combo.setAccessibleName("已保存的预设")
        self.load_button = QPushButton("使用")
        self.save_button = QPushButton("保存预设")
        self.load_button.setEnabled(False)
        for widget in [self.combo, self.load_button, self.save_button]:
            panel.preset_layout.addWidget(widget)
        self.load_button.clicked.connect(self._load)
        self.save_button.clicked.connect(self._save)

    def set_presets(self, records, selected=None):
        self.combo.clear()
        for record in records:
            self.combo.addItem(record["name"], record["preset_id"])
        if selected:
            self.combo.setCurrentIndex(self.combo.findData(selected))
        self.load_button.setEnabled(bool(records))

    def _load(self):
        if self.combo.currentData():
            self.load_requested.emit(self.combo.currentData())

    def _save(self):
        name, accepted = QInputDialog.getText(
            self.panel, "保存预设", "预设名称", text=self.combo.currentText()
        )
        if accepted and name.strip():
            self.save_requested.emit(name.strip())
