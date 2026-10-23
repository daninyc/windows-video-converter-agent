"""Capture a real Windows Qt window; invoke each scale in a separate process."""

import argparse
import ctypes
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", choices=["1", "1.5", "2"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--full", action="store_true", help="包含实际转换、助手和准备向导")
    args = parser.parse_args()
    if not args.worker:
        if os.name != "nt":
            parser.error("截图检查使用 Windows 实际显示环境")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetProcessDPIAware()
        base_scale = user32.GetDpiForSystem() / 96
        environment = dict(os.environ)
        environment.pop("QT_SCREEN_SCALE_FACTORS", None)
        environment["QT_SCALE_FACTOR"] = str(float(args.scale) / base_scale)
        windows_root = Path(os.environ["SystemRoot"])
        environment["PATH"] = os.pathsep.join(
            map(
                str,
                [
                    Path(sys.executable).parent,
                    Path(sys.base_prefix),
                    windows_root / "System32",
                    windows_root,
                ],
            )
        )
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "media_converter.devtools.capture_shell",
                "--worker",
                "--scale",
                args.scale,
                "--output",
                str(args.output),
                *(["--full"] if args.full else []),
            ],
            env=environment,
            check=False,
        ).returncode
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication

    from media_converter.config import AppPaths
    from media_converter.ui.main_window import MainWindow
    from media_converter.ui.theme import apply_theme

    app = QApplication([])
    apply_theme(app)
    args.output.mkdir(parents=True, exist_ok=True)
    window = MainWindow(AppPaths.from_argument(args.output / ("data-" + args.scale)).ensure())
    if not args.full:
        window.resize(window.minimumSize())
    store = bridge = setup = conversion = None
    if args.full:
        from media_converter.storage.local_store import LocalStore
        from media_converter.ui.agent_controller import AgentController
        from media_converter.ui.conversion_controller import ConversionController
        from media_converter.ui.runtime_bridge import RuntimeBridge
        from media_converter.ui.setup_wizard import SetupController

        store = LocalStore(window.paths.data_dir / "state.sqlite3")
        bridge = RuntimeBridge(window)
        conversion = ConversionController(window, store, bridge)
        window.controller = conversion
        window.agent_controller = AgentController(window, store, bridge, conversion)
        setup = SetupController(window, bridge, api_settings=window.agent_controller.api_settings)
        window.setup_controller = setup
    window.show()
    args.output.mkdir(parents=True, exist_ok=True)

    def capture():
        screen = window.screen()
        percent = round(float(args.scale) * 100)
        filename = f"{'desktop' if args.full else 'shell'}-{percent}.png"
        if abs(window.devicePixelRatioF() - float(args.scale)) > 0.001:
            print(json.dumps({"ok": False, "reason": "actual DPI differs from requested scale"}))
            app.exit(2)
            return
        image = window.grab()
        if not image.save(str(args.output / filename)):
            app.exit(2)
            return
        record = {
            "captured_at": datetime.now(UTC).isoformat(),
            "platform": platform.platform(),
            "qt_platform": app.platformName(),
            "requested_scale": args.scale,
            "device_pixel_ratio": window.devicePixelRatioF(),
            "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR"),
            "logical_window": [window.width(), window.height()],
            "image_pixels": [image.width(), image.height()],
            "screen": screen.name(),
            "screen_geometry": screen.geometry().getRect(),
            "available_geometry": screen.availableGeometry().getRect(),
            "logical_dpi": screen.logicalDotsPerInch(),
            "physical_dpi": screen.physicalDotsPerInch(),
            "method": (
                "QT_SCALE_FACTOR in separate real Windows process; not OS display setting change"
            ),
            "screenshot": filename,
        }
        from PySide6.QtCore import QPoint

        controls = [
            window.add_files_button,
            window.start_button,
            window.ai_toggle,
            window.setup_button,
        ]
        if args.full:
            controls += [
                window.agent_controller.panel.send_button,
                window.agent_controller.panel.input,
            ]
        record["controls"] = [
            {
                "text": w.text() if hasattr(w, "text") else w.accessibleName(),
                "visible": w.isVisible(),
                "visible_pixels": not w.visibleRegion().isEmpty(),
                "enabled": w.isEnabled(),
                "inside_window": window.rect().contains(w.mapTo(window, QPoint(0, 0)))
                and window.rect().contains(w.mapTo(window, QPoint(w.width() - 1, w.height() - 1))),
            }
            for w in controls
        ]
        if args.full:
            window._toggle_floating()
            record["float_return"] = window.agent_dock.isFloating()
            window._toggle_floating()
            record["float_return"] &= not window.agent_dock.isFloating()
            window.add_files_button.setFocus()
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest

            QTest.keyClick(window.add_files_button, Qt.Key.Key_Tab)
            record["keyboard_tab"] = app.focusWidget() is window.add_folder_button
            setup.open()

            # A real local empty-environment check; no simulated healthy result.
            def capture_setup():
                if setup.pending:
                    QTimer.singleShot(100, capture_setup)
                    return
                setup.dialog.grab().save(str(args.output / f"setup-{percent}.png"))
                record["setup_checked"] = setup.checked
                record["setup_screenshot"] = f"setup-{percent}.png"
                finish(record, percent)

            QTimer.singleShot(100, capture_setup)
            return
        finish(record, percent)

    def finish(record, percent):
        (args.output / f"{'desktop' if args.full else 'shell'}-{percent}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            "utf-8",
        )
        print(json.dumps(record, ensure_ascii=False), flush=True)
        window.close()
        if bridge:
            bridge.close()
        if store:
            store.close()
        app.quit()

    def when_ready():
        if conversion and (not conversion.ready or not window.agent_controller.current_id):
            QTimer.singleShot(100, when_ready)
            return
        if conversion and not conversion.model.rows:
            from media_converter.config import application_root

            conversion.import_paths((application_root() / "artifacts/fixtures/media/无音频.mp4",))
            QTimer.singleShot(500, when_ready)
            return
        if conversion and conversion.model.rows[0].asset.probe_status == "pending":
            QTimer.singleShot(100, when_ready)
            return
        if conversion:
            window.task_table.selectRow(0)
        capture()

    QTimer.singleShot(400, when_ready)
    exit_code = app.exec()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
