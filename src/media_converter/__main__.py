import argparse
import sys

from media_converter.config import AppPaths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows 视频转换器")
    parser.add_argument("--data-dir", help="本地运行数据目录，默认应用目录下的 data")
    args = parser.parse_args(argv)
    paths = AppPaths.from_argument(args.data_dir).ensure()
    from PySide6.QtCore import QCoreApplication, QEvent, QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from media_converter.common.logging import JsonlLogger
    from media_converter.storage.local_store import LocalStore
    from media_converter.ui.agent_controller import AgentController
    from media_converter.ui.conversion_controller import ConversionController
    from media_converter.ui.main_window import MainWindow
    from media_converter.ui.runtime_bridge import RuntimeBridge
    from media_converter.ui.setup_wizard import SetupController
    from media_converter.ui.theme import apply_theme

    app = QApplication.instance() or QApplication(sys.argv[:1])
    apply_theme(app)
    application_lock = QLockFile(str(paths.data_dir / "application.lock"))
    if not application_lock.tryLock(0):
        QMessageBox.warning(
            None,
            "无法锁定数据目录",
            "请检查是否已有窗口使用此目录，并确认目录可写；也可指定不同的数据目录。",
        )
        return 2
    window = MainWindow(paths)
    try:
        with (
            LocalStore(paths.data_dir / "state.sqlite3") as store,
            (paths.data_dir / "events.jsonl").open("a", encoding="utf-8") as log,
        ):
            bridge = RuntimeBridge(window, logger=JsonlLogger(log))
            controller = ConversionController(window, store, bridge)
            window.controller = controller
            window.agent_controller = AgentController(window, store, bridge, controller)
            window.setup_controller = SetupController(
                window, bridge, api_settings=window.agent_controller.api_settings
            )
            app.aboutToQuit.connect(controller.close)
            try:
                window.show()
                if (
                    not (paths.data_dir / "ai-components.json").exists()
                    or (paths.data_dir / "private-components.json").exists()
                ):
                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(0, window.setup_controller.open)
                return app.exec()
            finally:
                bridge.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        application_lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
