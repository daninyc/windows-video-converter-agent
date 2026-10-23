import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

from media_converter.devtools.bench_mcp import percentile, write_report


def benchmark(root, data_dir, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from media_converter.agent.models import Turn
    from media_converter.config import AppPaths
    from media_converter.mcp_client import MCPConnection
    from media_converter.media.models import ConversionSettings
    from media_converter.storage.conversations import ConversationStore
    from media_converter.storage.local_store import LocalStore
    from media_converter.ui.conversion_controller import ConversionController
    from media_converter.ui.main_window import MainWindow
    from media_converter.ui.runtime_bridge import RuntimeBridge
    from media_converter.ui.theme import apply_theme

    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    assert len(manifest["files"]) == 52
    paths = [root / row["path"] for row in manifest["files"]]
    app = QApplication([])
    apply_theme(app)
    work = Path("artifacts/video-pressure") / uuid4().hex
    work = work.resolve()
    store = LocalStore(work / "state.sqlite3")
    window = MainWindow(AppPaths(work).ensure())
    bridge = RuntimeBridge(window)
    controller = ConversionController(window, store, bridge)
    window.controller = controller
    window.show()
    started, previous = time.monotonic(), time.monotonic()
    intervals, active_intervals, ai_rows = [], [], []
    phase, cancel_at, state_at, stopped_at, notified_at = 0, None, None, None, None
    full_counts = None
    done = asyncio.Event()
    finished = False

    async def local_ai():
        chats = ConversationStore(store)
        chat = chats.create("视频压力本地工具")
        turn = chats.begin(chat.conversation_id, "本地压力", ConversionSettings())
        context = turn.context.model_copy(update={"deadline_at": time.time() + 7200})
        chats.save_turn(Turn(context=context, state="RUNNING"))
        connection = MCPConnection(work, components_dir=Path(data_dir).resolve())
        try:
            while not done.is_set():
                began = time.monotonic()
                result = await connection.call(
                    "rag_search", {"query": "MP4 默认编码", "top_k": 1}, context
                )
                ai_rows.append(
                    {
                        "ok": result["ok"] and not result.get("data", {}).get("limited", True),
                        "seconds": time.monotonic() - began,
                        "during_conversion": controller.active_batch is not None,
                    }
                )
                try:
                    await asyncio.wait_for(done.wait(), 5)
                except TimeoutError:
                    pass
        finally:
            await connection.close()

    def finish(reason=None):
        nonlocal finished
        if finished:
            return
        finished = True
        timer.stop()
        bridge.runtime._loop.call_soon_threadsafe(done.set)
        if not hasattr(controller, "jobs"):
            result = {"ok": False, "reason": reason or "initialization"}
        else:
            processor = controller.jobs.processor
            result = {
                "profile": "long-1080p",
                "fixtures": str(root / "manifest.json"),
                "fixture_complexity": manifest["content"],
                "full_queue": full_counts,
                "seconds": time.monotonic() - started,
                "qt_platform": app.platformName(),
                "heartbeat": {
                    "period_ms": 50,
                    "samples": len(intervals),
                    "p95_ms": percentile(intervals, 0.95),
                    "max_ms": max(intervals, default=0),
                    "during_conversion_samples": len(active_intervals),
                    "during_conversion_p95_ms": percentile(active_intervals, 0.95),
                },
                "cancel_ui_ms": None if notified_at is None else (notified_at - cancel_at) * 1000,
                "cancel_terminal_ms": None if state_at is None else (state_at - cancel_at) * 1000,
                "ffmpeg_stop_ms": None if stopped_at is None else (stopped_at - cancel_at) * 1000,
                "ffmpeg_peak": processor.peak_active,
                "conversion_pids": [e.pid for e in processor.evidence],
                "full_validations": len(controller.jobs.validations),
                "local_ai": ai_rows,
                "online_called": False,
                "reason": reason,
            }
            result["ok"] = bool(
                not reason
                and full_counts
                and full_counts["succeeded"] == 52
                and full_counts["failed"] == 0
                and result["full_validations"] == 52
                and processor.peak_active == 1
                and active_intervals
                and percentile(intervals, 0.95) <= 200
                and max(intervals) <= 1000
                and notified_at is not None
                and notified_at - cancel_at <= 1
                and stopped_at is not None
                and stopped_at - cancel_at <= 5
                and any(r["ok"] and r["during_conversion"] for r in ai_rows)
                and all(r["ok"] for r in ai_rows)
            )
            window.grab().save(str(work / "pressure-window.png"))
        write_report(output, result)
        window.close()
        bridge.close()
        store.close()
        app.exit(0 if result["ok"] else 2)

    def tick():
        nonlocal previous, phase, full_counts, cancel_at, state_at, stopped_at, notified_at
        now = time.monotonic()
        intervals.append((now - previous) * 1000)
        if controller.active_batch:
            active_intervals.append(intervals[-1])
        previous = now
        if now - started > 7200:
            finish("two hour safety timeout")
        elif phase == 0 and controller.ready:
            controller.import_paths(paths)
            bridge.submit(local_ai)
            phase = 1
        elif (
            phase == 1
            and len(window.task_model.rows) == 52
            and all(r.asset.probe_status == "succeeded" for r in window.task_model.rows)
        ):
            out = work / "outputs"
            out.mkdir()
            window.settings_panel.output_dir_edit.setText(str(out))
            window.settings_panel.output_dir_edit.editingFinished.emit()
            phase = 2
        elif phase == 2 and window.start_button.isEnabled():
            window.start_button.click()
            phase = 3
        elif phase == 3 and controller.finished_batches:
            full_counts = list(controller.finished_batches.values())[0]
            if full_counts["succeeded"] != 52:
                finish("full queue has failed/cancelled jobs")
                return

            async def cancellation_batch():
                asset = window.task_model.rows[0].asset
                source_root = await asyncio.to_thread(store.get_import_root, asset.root_id)
                plan = await asyncio.to_thread(
                    controller.planner.plan_one,
                    ConversionSettings(output_dir=work / "cancel-output"),
                    asset,
                    source_root,
                )
                return await controller.jobs.start_batch((plan,), uuid4().hex)

            controller._submit(cancellation_batch, controller._started)
            phase = 4
        elif phase == 4 and controller.active_batch and controller.jobs.processor.active_count:
            # Wait for a real owned conversion process, then use the ordinary GUI action.
            cancel_at = now
            window.cancel_batch_button.click()
            phase = 5
        elif phase == 5:
            if notified_at is None and "已请求取消" in window.notice_label.text():
                notified_at = now
            if stopped_at is None and controller.jobs.processor.active_count == 0:
                stopped_at = now
            if controller.active_batch is None:
                state_at = now
                # Fast completion can replace the acknowledgement within one GUI tick.
                notified_at = notified_at or now
                finish()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(50)
    app.exec()
    return json.loads(Path(output).read_text("utf-8"))
