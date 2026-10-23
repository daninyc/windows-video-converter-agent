import subprocess
import sys

import pytest

pytestmark = pytest.mark.gui


def test_installed_gui_entry_exits_without_ai_or_worker_threads(tmp_path):
    script = """
import sys, threading
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from media_converter.__main__ import main
app = QApplication([])
QTimer.singleShot(200, app.quit)
assert main(['--data-dir', sys.argv[1]]) == 0
assert 'torch' not in sys.modules
assert 'mcp' not in sys.modules
names = {t.name for t in threading.enumerate()}
assert not names.intersection({'media-async-runtime','local-store-writer'})
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "state.sqlite3").is_file()


def test_gui_can_convert_with_optional_ai_packages_unavailable(tmp_path):
    script = """
import sys, threading
for name in ('httpx', 'mcp', 'sentence_transformers', 'torch', 'qdrant_client', 'mysql'):
    sys.modules[name] = None
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from media_converter.config import AppPaths
from media_converter.storage.local_store import LocalStore
from media_converter.ui.main_window import MainWindow
from media_converter.ui.conversion_controller import ConversionController
from media_converter.ui.runtime_bridge import RuntimeBridge
from media_converter.ui.setup_wizard import SetupController
app = QApplication([])
paths = AppPaths.from_argument(sys.argv[1]).ensure()
store = LocalStore(paths.data_dir/'state.sqlite3')
window = MainWindow(paths)
bridge = RuntimeBridge(window)
conversion = ConversionController(window,store,bridge)
window.controller = conversion
window.setup_controller = SetupController(window,bridge)
window.show()
window.setup_controller.open()
def finish():
    if not conversion.ready or not window.setup_controller.checked:
        QTimer.singleShot(100,finish)
        return
    assert window.add_files_button.isEnabled()
    assert not window.setup_controller.service.report['ok']
    window.close()
    bridge.close()
    store.close()
    app.quit()
QTimer.singleShot(100,finish)
app.exec()
names = {t.name for t in threading.enumerate()}
assert not {'local-store-writer','media-async-runtime'}.intersection(names)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
