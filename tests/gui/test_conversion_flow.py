import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog

from media_converter.config import AppPaths, application_root
from media_converter.jobs.models import JobState
from media_converter.storage.local_store import LocalStore
from media_converter.ui.conversion_controller import ConversionController
from media_converter.ui.loss_confirmation import LossConfirmationDialog
from media_converter.ui.main_window import MainWindow
from media_converter.ui.runtime_bridge import RuntimeBridge
from media_converter.ui.theme import apply_theme

pytestmark = pytest.mark.gui
ACCEPTANCE_ROOT = application_root() / "artifacts/conversion-acceptance" / str(uuid4())


@pytest.fixture
def connected_window(qtbot, qapp, tmp_path):
    apply_theme(qapp)
    paths = AppPaths.from_argument(tmp_path / "data").ensure()
    store = LocalStore(paths.data_dir / "state.sqlite3")
    window = MainWindow(paths)
    bridge = RuntimeBridge(window)
    controller = ConversionController(window, store, bridge)
    window.controller = controller
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: controller.ready, timeout=15000)
    try:
        yield window, controller, store
    finally:
        window.close()
        bridge.close()
        store.close()


@pytest.mark.parametrize("container", ["mp4", "mkv", "webm"])
def test_real_desktop_conversion_flow(
    container, connected_window, qtbot, fixture_root, monkeypatch
):
    window, controller, store = connected_window
    case = ACCEPTANCE_ROOT / container
    case.mkdir(parents=True)
    output = case / "outputs"
    output.mkdir()
    source = fixture_root / "media/双音轨 双字幕.mkv"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    bad = fixture_root / "media/损坏.mp4"
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a: ([str(source), str(bad)], ""))
    qtbot.mouseClick(window.add_files_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: (
            len(window.task_model.rows) == 2
            and all(
                row.asset.probe_status in ("succeeded", "failed") for row in window.task_model.rows
            )
        ),
        timeout=15000,
    )
    panel = window.settings_panel
    panel.container_combo.setCurrentIndex(panel.container_combo.findData(container))
    panel.output_dir_edit.setText(str(output))
    panel.output_dir_edit.editingFinished.emit()
    qtbot.waitUntil(window.start_button.isEnabled)
    window.task_table.selectRow(1)
    assert "损坏.mp4" in window.details_panel.toPlainText()
    window.task_table.selectRow(0)
    assert "双音轨" in window.details_panel.toPlainText()
    confirmed = []
    timer = QTimer()
    timer.setInterval(10)

    def consent():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, LossConfirmationDialog) and not confirmed:
            dialog.grab().save(str(case / "loss-confirmation.png"))
            confirmed.append(dialog.details.toPlainText())
            qtbot.mouseClick(
                dialog.consent_checkbox,
                Qt.MouseButton.LeftButton,
                pos=QPoint(10, dialog.consent_checkbox.height() // 2),
            )
            qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)

    timer.timeout.connect(consent)
    timer.start()
    try:
        qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
        controller.start()
        qtbot.waitUntil(lambda: bool(controller.finished_batches), timeout=30000)
    finally:
        timer.stop()
    assert len(controller.finished_batches) == 1
    assert next(iter(controller.finished_batches.values())) == {
        "total": 1,
        "completed": 1,
        "succeeded": 1,
        "failed": 0,
        "cancelled": 0,
    }
    row = window.task_model.rows[0]
    assert row.attempt.state == JobState.SUCCEEDED
    assert window.task_model.rows[1].asset.probe_status == "failed"
    assert window.task_model.rows[1].attempt is None
    assert Path(row.attempt.output_path).suffix == "." + container
    assert (
        controller.jobs.processor.peak_active == 1 and len(controller.jobs.processor.evidence) == 1
    )
    assert bool(confirmed) == (container != "mkv")
    assert before == hashlib.sha256(source.read_bytes()).hexdigest()
    window.task_table.selectRow(0)
    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url) or True)
    qtbot.mouseClick(window.open_button, Qt.MouseButton.LeftButton)
    assert Path(urls[0].toLocalFile()) == Path(row.attempt.output_path).parent
    window.grab().save(str(case / "completed.png"))
    plan = store.get_plan(row.attempt.plan_id)
    evidence = {
        "method": (
            "automated real Qt Widgets operation; real FFmpeg/ffprobe; "
            "OS folder URL dispatch asserted"
        ),
        "container": container,
        "attempt": row.attempt.model_dump(mode="json"),
        "source_sha256_before": before,
        "source_sha256_after": hashlib.sha256(source.read_bytes()).hexdigest(),
        "plan": plan.model_dump(mode="json"),
        "validation": controller.jobs.validations[row.attempt.attempt_id],
        "ffmpeg_peak_concurrency": controller.jobs.processor.peak_active,
        "processes": [asdict(process) for process in controller.jobs.processor.evidence],
        "consent_dialog_shown": bool(confirmed),
        "output_sha256": hashlib.sha256(Path(row.attempt.output_path).read_bytes()).hexdigest(),
    }
    (case / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), "utf-8")


@pytest.mark.parametrize("whole_batch", [False, True])
def test_real_gui_cancel_buttons(whole_batch, connected_window, qtbot, fixture_root, tmp_path):
    from media_converter.media.models import ConversionSettings, Resolution

    window, controller, store = connected_window
    controller.import_paths(
        [fixture_root / "media/中文 空格/基础.mp4", fixture_root / "media/无音频.mp4"]
    )
    qtbot.waitUntil(
        lambda: (
            len(window.task_model.rows) == 2
            and all(row.asset.probe_status == "succeeded" for row in window.task_model.rows)
        ),
        timeout=15000,
    )
    panel = window.settings_panel
    panel.container_combo.setCurrentIndex(panel.container_combo.findData("webm"))
    data = panel.validation().settings.model_dump()
    data.update(
        output_dir=tmp_path / "cancel-outputs", resolution=Resolution(width=1920, height=1080)
    )
    panel.set_settings(ConversionSettings.model_validate(data))
    qtbot.waitUntil(window.start_button.isEnabled)
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(controller.jobs.processor.evidence), timeout=10000)
    panel.container_combo.setCurrentIndex(panel.container_combo.findData("mp4"))
    qtbot.mouseClick(
        window.cancel_batch_button if whole_batch else window.cancel_button,
        Qt.MouseButton.LeftButton,
    )
    qtbot.waitUntil(lambda: bool(controller.finished_batches), timeout=30000)
    rows = window.task_model.rows
    assert rows[0].attempt.state == JobState.CANCELLED
    assert rows[1].attempt.state == (JobState.CANCELLED if whole_batch else JobState.SUCCEEDED)
    if not whole_batch:
        assert Path(rows[1].attempt.output_path).suffix == ".webm"


def test_close_running_window_stops_owned_process_and_saves_state(
    connected_window, qtbot, fixture_root, tmp_path
):
    window, controller, store = connected_window
    controller.import_paths([fixture_root / "media/中文 空格/基础.mp4"])
    qtbot.waitUntil(
        lambda: (
            bool(window.task_model.rows)
            and window.task_model.rows[0].asset.probe_status == "succeeded"
        ),
        timeout=15000,
    )
    panel = window.settings_panel
    panel.container_combo.setCurrentIndex(panel.container_combo.findData("webm"))
    panel.resolution_combo.setCurrentIndex(3)
    panel.output_dir_edit.setText(str(tmp_path / "outputs"))
    panel.output_dir_edit.editingFinished.emit()
    qtbot.waitUntil(window.start_button.isEnabled)
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(controller.jobs.processor.evidence), timeout=10000)
    window.close()
    assert controller.jobs.processor.active_count == 0
    assert not controller.bridge.runtime._thread.is_alive()
    attempts = store.list_attempts()
    assert attempts and all(
        attempt.state in {JobState.CANCELLED, JobState.SUCCEEDED} for attempt in attempts
    )
    for attempt in attempts:
        assert not store.get_plan(attempt.plan_id).temporary_path.parent.exists()
