from PySide6.QtCore import QObject, Qt, Signal, Slot

from media_converter.common.context import CallContext
from media_converter.common.logging import JsonlLogger
from media_converter.services.async_runtime import AsyncRuntime


class RuntimeBridge(QObject):
    event_received = Signal(object)
    _incoming = Signal(object)

    def __init__(self, parent=None, logger: JsonlLogger | None = None):
        super().__init__(parent)
        self.logger = logger or JsonlLogger()
        self._incoming.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self.runtime = AsyncRuntime(self._incoming.emit)

    @Slot(object)
    def _deliver(self, event):
        self.logger.event(
            "runtime.finished",
            event.context,
            task_id=event.task_id,
            state=event.state,
            error_code=event.error.code if event.error else None,
        )
        self.event_received.emit(event)

    def submit(self, factory, context: CallContext | None = None) -> str:
        return self.runtime.submit(factory, context)

    def cancel(self, task_id: str) -> bool:
        return self.runtime.cancel(task_id)

    def close(self, before_close=None):
        self.runtime.close(before_close)
