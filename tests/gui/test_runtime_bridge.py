import asyncio
import threading

import pytest
from PySide6.QtCore import QThread, QTimer

from media_converter.common.errors import AppError
from media_converter.ui.runtime_bridge import RuntimeBridge

pytestmark = pytest.mark.gui


def test_delayed_work_keeps_gui_alive_and_delivers_on_gui_thread(qtbot, qapp):
    bridge = RuntimeBridge()
    ticks, events, threads = [], [], []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    bridge.event_received.connect(
        lambda event: (events.append(event), threads.append(QThread.currentThread()))
    )

    async def work():
        assert threading.current_thread().name == "media-async-runtime"
        await asyncio.sleep(0.15)
        return "done"

    try:
        task_id = bridge.submit(work)
        qtbot.waitUntil(lambda: len(events) == 1)
        assert len(ticks) >= 3
        assert threads == [qapp.thread()]
        assert events[0].task_id == task_id and events[0].data == "done"
    finally:
        timer.stop()
        bridge.close()
    assert not bridge.runtime._thread.is_alive()


def test_exception_cancellation_races_and_shutdown(qtbot):
    bridge = RuntimeBridge()
    events = []
    bridge.event_received.connect(events.append)

    async def fail():
        raise ValueError("SENTINEL_SECRET")

    async def slow():
        await asyncio.sleep(60)

    failure_id = bridge.submit(fail)
    cancelled_id = bridge.submit(slow)
    bridge.cancel(cancelled_id)
    qtbot.waitUntil(lambda: len(events) == 2)
    assert {event.state for event in events} == {"failed", "cancelled"}
    assert next(e for e in events if e.task_id == failure_id).error.code == "INTERNAL_ERROR"
    assert not bridge.cancel(cancelled_id)
    ids = [bridge.submit(lambda: asyncio.sleep(0)) for _ in range(20)]
    for task_id in ids:
        bridge.cancel(task_id)
    qtbot.waitUntil(lambda: len(events) == 22)
    assert len({event.task_id for event in events}) == 22
    active = bridge.submit(slow)
    bridge.close()
    qtbot.waitUntil(lambda: any(event.task_id == active for event in events))
    assert not bridge.runtime._thread.is_alive()
    with pytest.raises(AppError):
        bridge.submit(slow)
