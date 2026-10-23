import argparse
import json
import sys
import time
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from media_converter.config import AppPaths
    from media_converter.storage.local_store import LocalStore
    from media_converter.ui.conversion_controller import ConversionController
    from media_converter.ui.main_window import MainWindow
    from media_converter.ui.runtime_bridge import RuntimeBridge
    from media_converter.ui.theme import apply_theme

    app = QApplication([])
    apply_theme(app)
    paths = AppPaths(args.data_dir.resolve()).ensure()
    store = LocalStore(paths.data_dir / "state.sqlite3")
    window = MainWindow(paths)
    bridge = RuntimeBridge(window)
    controller = ConversionController(window, store, bridge)
    window.controller = controller
    window.show()
    phase = 0
    started = time.monotonic()

    def tick():
        nonlocal phase
        if time.monotonic() - started > 120:
            finish({"ok": False, "reason": "timeout"})
            return
        if phase == 0 and controller.ready:
            controller.import_paths([args.source])
            phase = 1
        elif (
            phase == 1
            and window.task_model.rows
            and window.task_model.rows[0].asset.probe_status == "succeeded"
        ):
            out = paths.data_dir / "outputs"
            out.mkdir(exist_ok=True)
            window.settings_panel.output_dir_edit.setText(str(out))
            window.settings_panel.output_dir_edit.editingFinished.emit()
            phase = 2
        elif phase == 2 and window.start_button.isEnabled():
            window.start_button.click()
            phase = 3
        elif phase == 3 and controller.finished_batches:
            row = window.task_model.rows[0]
            image = paths.data_dir / "package-window.png"
            window.grab().save(str(image))
            finish(
                {
                    "ok": row.attempt.state == "SUCCEEDED",
                    "frozen": getattr(sys, "frozen", False),
                    "qt_platform": app.platformName(),
                    "output": row.attempt.output_path,
                    "validation": controller.jobs.validations.get(row.attempt.attempt_id),
                    "torch_loaded": "torch" in sys.modules,
                    "python": sys.version.split()[0],
                }
            )

    def finish(result):
        timer.stop()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
        window.close()
        bridge.close()
        store.close()
        app.exit(0 if result["ok"] else 2)

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(50)
    return app.exec()
