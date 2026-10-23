from media_converter.config import application_root
from media_converter.services.component_manifest import inventory
from media_converter.services.downloads import Downloader
from media_converter.services.mysql_instance import MySQLInstance
from media_converter.services.preparer import free_port
from media_converter.services.process_manager import ProcessManager, process_identity
from media_converter.storage.mysql_driver import connector
from media_converter.storage.mysql_sync import mysql_config


async def test_official_mysql_archive_new_private_data_directory(
    tmp_path, record_property, monkeypatch
):
    item = next(a for a in inventory() if a.name == "mysql")
    folder = await Downloader(tmp_path / "payload").install(
        item, cached=application_root() / "environment/downloads/mysql.zip"
    )
    root = tmp_path / "instance"
    instance = MySQLInstance(root, ProcessManager(root))
    record = None
    try:
        record = await instance.prepare(
            next(folder.rglob("mysqld.exe")), free_port(), application_root() / "knowledge"
        )
        with connector.connect(**mysql_config(root, "reader")) as db:
            cursor = db.cursor()
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            assert version.startswith(item.version)
            record_property("official_mysql_version", version)
    finally:
        await instance.stop()
    assert record and process_identity(record["pid"]) is None
    import asyncio

    import pytest

    original = asyncio.create_subprocess_exec
    started, processes = asyncio.Event(), []

    async def observe(*args, **kwargs):
        assert kwargs["env"]["TEMP"] == str(interrupted_root / "tmp")
        assert kwargs["env"]["TMP"] == str(interrupted_root / "tmp")
        process = await original(*args, **kwargs)
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observe)
    interrupted_root = tmp_path / "cancelled-instance"
    interrupted = MySQLInstance(interrupted_root, ProcessManager(interrupted_root))
    task = asyncio.create_task(
        interrupted.prepare(
            next(folder.rglob("mysqld.exe")), free_port(), application_root() / "knowledge"
        )
    )
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes and all(p.returncode is not None for p in processes)
    assert not (interrupted_root / "components/mysql-data").exists()
    assert not list((interrupted_root / "private").glob("*.dpapi"))
