import socket
import sys
from pathlib import Path

import pytest

from media_converter.common.errors import AppError
from media_converter.config import application_root
from media_converter.services.health import HealthService
from media_converter.services.mysql_instance import MySQLInstance
from media_converter.services.process_manager import ProcessManager, listener_pid, process_identity

pytestmark = pytest.mark.integration


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.mark.parametrize("monitor", [False, True])
async def test_private_process_start_reuse_conflict_and_owned_stop(tmp_path, monitor):
    manager, port = ProcessManager(tmp_path), free_port()
    executable = Path(sys._base_executable).resolve()
    args = [
        "-c",
        f"import socket,time; s=socket.socket(); s.bind(('127.0.0.1',{port})); "
        "s.listen(); time.sleep(90)",
    ]
    if monitor:
        import json

        args = [
            "-c",
            "import subprocess; p=subprocess.Popen("
            + json.dumps([str(executable), *args])
            + "); p.wait()",
        ]
    record = await manager.start("probe", executable, args, port)
    try:
        events = []
        manager.notify = events.append
        assert record["pid"] == listener_pid(port)
        assert (record["pid"] != record["launcher_pid"]) is monitor
        assert (await manager.start("probe", executable, args, port))["reused"]
        with pytest.raises(AppError):
            await manager.start("foreign", executable, args, port)
        assert events[-1]["state"] == "blocked" and str(port) in events[-1]["message"]
        assert process_identity(record["pid"])
    finally:
        assert await manager.stop("probe")
    assert process_identity(record["pid"]) is None


async def test_private_mysql_initialization_and_clean_shutdown(tmp_path, record_property):
    executable = Path(r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe")
    if not executable.exists():
        pytest.skip("本机无 MySQL 二进制；不得将 skip 计入验收")
    instance = MySQLInstance(tmp_path, ProcessManager(tmp_path))
    port = free_port()
    try:
        record = await instance.prepare(executable, port, application_root() / "knowledge")
        assert record["port"] == port
        assert (tmp_path / "mysql.json").is_file()
        assert not (tmp_path / "private/mysql-init.sql").exists()
        import mysql.connector

        from media_converter.storage.mysql_sync import mysql_config

        with mysql.connector.connect(**mysql_config(tmp_path, "reader")) as db:
            cursor = db.cursor()
            cursor.execute("SELECT COUNT(*) FROM technical_rules")
            assert cursor.fetchone()[0] > 0
        record_property("isolated_mysql_port", port)
    finally:
        await instance.stop()


async def test_doctor_real_local_components_without_online_or_history_mutation(ai_source):
    state = (ai_source / "state.sqlite3").read_bytes()
    report = await HealthService(ai_source).inspect()
    assert report["ok"], report
    assert not report["online_called"]
    assert {check["component"] for check in report["checks"]} == {
        "video",
        "mcp",
        "knowledge",
        "mysql",
        "files",
    }
    assert (ai_source / "state.sqlite3").read_bytes() == state
