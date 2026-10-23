from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

STYLE = """
QWidget { color: #243449; font-family: 'Microsoft YaHei UI'; font-size: 13px; }
QMainWindow, QDockWidget { background: #f4f6f9; }
QFrame#panel { background: #ffffff; border: 1px solid #dce2ea; border-radius: 8px; }
QLabel#heading { font-size: 25px; font-weight: 600; color: #172b46; }
QLabel#section { font-size: 16px; font-weight: 600; }
QLabel#muted { color: #65748a; }
QLabel#emptyTitle { font-size: 19px; font-weight: 600; color: #42556e; }
QLabel#badge { color: #24604c; background: #e7f3ec; border-radius: 5px; padding: 6px 10px; }
QPushButton { border: 1px solid #cbd5e1; background: white; border-radius: 5px;
              padding: 7px 12px; min-height: 18px; }
QPushButton:hover { background: #edf4ff; border-color: #3874bd; }
QPushButton:focus { border: 2px solid #2469ba; }
QPushButton:disabled { color: #8b96a5; background: #f1f3f6; border-color: #e0e5eb; }
QPushButton#primary { color: white; background: #2869b4; border: 1px solid #2869b4; }
QPushButton#primary:disabled { color: #929eaf; background: #e3e8ef; border-color: #e3e8ef; }
QComboBox, QLineEdit, QTextEdit { background: white; border: 1px solid #d4dde8;
                               border-radius: 4px; padding: 6px; min-height: 20px; }
QComboBox:disabled, QLineEdit:disabled { background: #f5f7fa; color: #7c899b; }
QGroupBox { border: 0; margin-top: 24px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 0; top: 3px; }
QHeaderView::section { background: #f5f7fa; color: #607086; border: 0;
                       border-bottom: 1px solid #e1e7ef; padding: 8px; }
QTableWidget, QTableView { background: white; border: 0; gridline-color: #edf0f5; }
QTableView::item:selected { background: #e5effc; color: #172b46; }
QWidget#settings_panel { background: white; }
QProgressBar { border: 0; border-radius: 3px; background: #e6ebf2;
               height: 6px; max-height: 6px; }
QProgressBar::chunk { background: #2869b4; border-radius: 3px; }
QDockWidget::title { background: #edf1f6; padding: 8px; font-weight: 600; }
QSplitter::handle { background: transparent; width: 10px; height: 10px; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#f4f6f9",
        QPalette.ColorRole.WindowText: "#243449",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f5f7fa",
        QPalette.ColorRole.Text: "#243449",
        QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#243449",
        QPalette.ColorRole.Highlight: "#dceaff",
        QPalette.ColorRole.HighlightedText: "#172b46",
        QPalette.ColorRole.Accent: "#2869b4",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#243449",
    }.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)
