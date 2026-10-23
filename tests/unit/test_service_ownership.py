import json
from unittest.mock import Mock

import pytest

from media_converter.common.errors import AppError, ErrorCode
from media_converter.services.process_manager import ProcessManager

pytestmark = pytest.mark.unit


async def test_reused_pid_never_stopped(tmp_path, monkeypatch):
    manager = ProcessManager(tmp_path)
    path = manager.record_path("test")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"pid": 100, "created": 1, "executable": "old.exe"}))
    monkeypatch.setattr(
        "media_converter.services.process_manager.process_identity",
        lambda pid: {"pid": 100, "created": 2, "executable": "new.exe"},
    )
    stop = Mock()
    monkeypatch.setattr("media_converter.services.process_manager.subprocess.run", stop)
    with pytest.raises(AppError) as error:
        await manager.stop("test")
    assert error.value.info.code == ErrorCode.ACCESS_DENIED
    stop.assert_not_called()


def test_service_names_cannot_escape_root(tmp_path):
    for name in ("../mysql", "x/y", "x;delete", "C:\\foo"):
        with pytest.raises(AppError):
            ProcessManager(tmp_path).record_path(name)
