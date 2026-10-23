import json
from unittest.mock import AsyncMock, Mock

import pytest

from media_converter.common.errors import AppError, ErrorCode
from media_converter.services.preparer import SetupService

pytestmark = pytest.mark.unit


def prepared_service(tmp_path, monkeypatch):
    health = Mock(inspect=AsyncMock(return_value={"ok": True}))
    service = SetupService(tmp_path, health=health)
    monkeypatch.setattr(service, "plan", lambda: {"worker_available": True})
    build = AsyncMock()
    monkeypatch.setattr("media_converter.worker_runtime.build_index", build)
    return service, build, health


async def test_reuse_private_components_restores_services_before_index_and_after_close(
    tmp_path, monkeypatch
):
    (tmp_path / "private-components.json").write_text(json.dumps({"mysql_port": 3308}))
    service, build, health = prepared_service(tmp_path, monkeypatch)
    events = []

    async def restore(emit):
        events.append("restore")

    async def index(*args):
        events.append("index")

    async def inspect(**kwargs):
        events.append("inspect")
        return {"ok": True}

    async def stop():
        events.append("stop")

    monkeypatch.setattr(service, "_private", restore)
    monkeypatch.setattr(service, "stop_owned", stop)
    build.side_effect = index
    health.inspect.side_effect = inspect
    for _ in range(2):
        assert (await service.prepare(mode="reuse"))["ok"]
        assert service.current is None
        await service.close()
    assert events == ["restore", "index", "inspect", "stop"] * 2


async def test_reuse_external_components_does_not_start_private_services(tmp_path, monkeypatch):
    for name in ("ai-components.json", "mysql.json"):
        (tmp_path / name).write_text("{}")
    service, build, health = prepared_service(tmp_path, monkeypatch)
    private = AsyncMock()
    monkeypatch.setattr(service, "_private", private)
    assert (await service.prepare(mode="reuse"))["ok"]
    private.assert_not_awaited()
    build.assert_awaited_once()
    health.inspect.assert_awaited_once()


@pytest.mark.parametrize("mode", ["reuse", "private"])
@pytest.mark.parametrize("private_marker", [False, True])
def test_prepare_cli_closes_services_in_both_modes(tmp_path, monkeypatch, mode, private_marker):
    from media_converter.devtools.__main__ import main

    if private_marker:
        (tmp_path / "private-components.json").write_text("{}")
    service = Mock(root=tmp_path)
    service.prepare = AsyncMock(return_value={"ok": True})
    service.close = AsyncMock()
    monkeypatch.setattr(
        "media_converter.services.preparer.SetupService", Mock(return_value=service)
    )
    output = tmp_path / "result.json"
    assert (
        main(
            [
                "prepare",
                "--components",
                "ai",
                "--mode",
                mode,
                "--data-dir",
                str(tmp_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    service.close.assert_awaited_once()
    result = json.loads(output.read_text("utf-8"))
    assert result.get("private_services_stopped_after_check", False) == private_marker
    assert not (tmp_path / "application.lock").exists()


@pytest.mark.parametrize("mode", ["reuse", "private"])
def test_prepare_cli_closes_services_after_failure(tmp_path, monkeypatch, mode):
    from media_converter.devtools.__main__ import main

    service = Mock(root=tmp_path)
    service.prepare = AsyncMock(side_effect=AppError(ErrorCode.DEPENDENCY_UNAVAILABLE))
    service.close = AsyncMock()
    monkeypatch.setattr(
        "media_converter.services.preparer.SetupService", Mock(return_value=service)
    )
    assert main(["prepare", "--components", "ai", "--mode", mode, "--data-dir", str(tmp_path)]) == 2
    service.close.assert_awaited_once()
    assert not (tmp_path / "application.lock").exists()
