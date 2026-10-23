import asyncio
import threading

import pytest
from PySide6.QtCore import Qt

from media_converter.common.errors import AppError, ErrorCode
from media_converter.config import AppPaths
from media_converter.storage.local_store import LocalStore
from media_converter.ui.conversion_controller import ConversionController
from media_converter.ui.main_window import MainWindow
from media_converter.ui.runtime_bridge import RuntimeBridge
from media_converter.ui.setup_wizard import SetupController
from media_converter.ui.theme import apply_theme

pytestmark = pytest.mark.gui


class ControlledSetup:
    """UI fault/latency substitute; real preparation is tested in integration separately."""

    def __init__(self):
        self.calls = 0
        self.fail = False
        self.gate = threading.Event()
        self.cancelled = False
        self.history = []

    def plan(self):
        return {"download_bytes": 100, "space_bytes": 200, "free_bytes": 1000, "artifacts": []}

    async def inspect(self, emit):
        emit({"component": "video", "ok": True})
        emit({"component": "knowledge", "ok": False, "message": "缺少模型", "action": "准备组件"})
        return {"ok": False}

    async def prepare(self, *, mode, emit):
        self.calls += 1
        self.cancelled = False
        emit({"component": "models", "state": "downloading", "bytes": 10, "total": 100})
        while not self.gate.is_set():
            if self.cancelled:
                raise asyncio.CancelledError
            await asyncio.sleep(0.01)
        if self.fail:
            raise AppError(ErrorCode.DISK_FULL)
        return {"ok": True}

    def cancel(self):
        self.cancelled = True

    async def close(self):
        self.cancel()
        self.gate.set()


@pytest.fixture
def setup_window(qtbot, qapp, tmp_path):
    apply_theme(qapp)
    window = MainWindow(AppPaths.from_argument(tmp_path).ensure())
    store = LocalStore(tmp_path / "state.sqlite3")
    bridge = RuntimeBridge(window)
    conversion = ConversionController(window, store, bridge)
    window.controller = conversion
    service = ControlledSetup()
    setup = SetupController(window, bridge, service=service)
    window.setup_controller = setup
    qtbot.addWidget(window)
    window.show()
    setup.open()
    qtbot.waitUntil(lambda: setup.checked and conversion.ready, timeout=15000)
    try:
        yield window, conversion, setup, service
    finally:
        service.gate.set()
        window.close()
        bridge.close()
        store.close()


def test_missing_ai_keeps_conversion_available_and_has_actions(setup_window):
    window, conversion, setup, _ = setup_window
    assert window.add_files_button.isEnabled() and window.settings_panel.isEnabled()
    assert not window.start_button.isEnabled()  # No imported media yet.
    assert "部分能力" in setup.dialog.summary.text()
    assert setup.dialog.rows["knowledge"].text(2) == "缺少模型；准备组件"
    assert setup.dialog.prepare_button.isEnabled()


def test_close_reopen_preserves_single_preparation_and_cancel(setup_window, qtbot):
    _, _, setup, service = setup_window
    dialog = setup.dialog
    qtbot.mouseClick(dialog.prepare_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: service.calls == 1)
    dialog.close()
    setup.open()
    assert setup.dialog is dialog and service.calls == 1 and setup.pending
    qtbot.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: setup.pending is None)
    assert "取消" in dialog.summary.text() and dialog.prepare_button.isEnabled()


def test_failure_retry_and_connection_settings_entry(setup_window, qtbot):
    _, _, setup, service = setup_window
    called = []
    setup.api_settings = lambda: called.append(True)
    # Signal binds the initial callback; test the dialog entry with a fresh explicit handler.
    setup.dialog.api_button.clicked.disconnect()
    setup.dialog.api_button.clicked.connect(setup.api_settings)
    qtbot.mouseClick(setup.dialog.api_button, Qt.MouseButton.LeftButton)
    assert called == [True]
    service.fail = True
    service.gate.set()
    qtbot.mouseClick(setup.dialog.prepare_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: setup.pending is None)
    assert "空间不足" in setup.dialog.summary.text()
    service.fail = False
    qtbot.mouseClick(setup.dialog.prepare_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: setup.pending is None)
    assert service.calls == 2 and "已就绪" in setup.dialog.summary.text()


def test_real_conversion_completes_while_preparation_is_waiting(
    setup_window, qtbot, fixture_root, tmp_path
):
    window, conversion, setup, service = setup_window
    conversion.import_paths((fixture_root / "media/无音频.mp4",))
    qtbot.waitUntil(
        lambda: (
            bool(window.task_model.rows)
            and window.task_model.rows[0].asset.probe_status == "succeeded"
        ),
        timeout=15000,
    )
    output = tmp_path / "outputs"
    output.mkdir()
    window.settings_panel.output_dir_edit.setText(str(output))
    window.settings_panel.output_dir_edit.editingFinished.emit()
    qtbot.waitUntil(window.start_button.isEnabled)
    qtbot.mouseClick(setup.dialog.prepare_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: service.calls == 1)
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(conversion.finished_batches), timeout=30000)
    assert next(iter(conversion.finished_batches.values()))["succeeded"] == 1
    assert setup.pending is not None and not service.gate.is_set()
    assert list(output.glob("*.mp4"))
    service.gate.set()
    qtbot.waitUntil(lambda: setup.pending is None)
