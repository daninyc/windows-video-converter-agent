import asyncio
import json
import secrets
import shutil
from pathlib import Path

from media_converter.common.errors import AppError, ErrorCode
from media_converter.common.process import capture_process
from media_converter.common.windows_files import sharing_retry
from media_converter.storage.credentials import CredentialStore
from media_converter.storage.mysql_sync import initialize_mysql


class MySQLInstance:
    def __init__(self, data_dir, manager):
        self.root, self.manager = Path(data_dir).resolve(), manager
        self.marker = self.root / "private/mysql-instance.json"
        self.credentials = CredentialStore(self.root / "private")

    async def prepare(self, executable, port, rules_root):
        executable = Path(executable).resolve()
        folder = self.root / "components/mysql-data"
        config = self.root / "components/mysql.ini"
        if await asyncio.to_thread(self.manager.inspect, "mysql"):
            return {"reused": True}
        if self.marker.exists():
            state = json.loads(self.marker.read_text(encoding="utf-8"))
            if state["executable"] != str(executable) or state["port"] != port:
                raise AppError(ErrorCode.ACCESS_DENIED)
            password = self.credentials.read(state["credential_ref"])
        else:
            if (folder.exists() and any(folder.iterdir())) or (self.root / "mysql.json").exists():
                raise AppError(ErrorCode.ACCESS_DENIED)
            folder.mkdir(parents=True, exist_ok=True)
            (self.root / "logs").mkdir(exist_ok=True)
            temporary = self.root / "tmp"
            temporary.mkdir(exist_ok=True)
            password = secrets.token_urlsafe(32)
            reference = self.credentials.save(password)
            try:
                await capture_process(
                    executable,
                    [
                        "--no-defaults",
                        f"--basedir={executable.parent.parent}",
                        f"--datadir={folder}",
                        "--initialize-insecure",
                        f"--log-error={self.root / 'logs/mysql.log'}",
                    ],
                    timeout=90,
                    environment={"TEMP": str(temporary), "TMP": str(temporary)},
                )
            except BaseException:
                # Only this newly created, previously empty private directory belongs to this run.
                if folder.resolve().is_relative_to(self.root):
                    await asyncio.to_thread(shutil.rmtree, folder)
                self.credentials.clear(reference)
                raise
            state = {
                "executable": str(executable),
                "port": port,
                "credential_ref": reference,
                "provisioned": False,
            }
            self.marker.write_text(json.dumps(state), encoding="utf-8")
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            "[mysqld]\n"
            + "\n".join(
                [
                    f"basedir={executable.parent.parent.as_posix()}",
                    f"datadir={folder.as_posix()}",
                    f"port={port}",
                    "bind-address=127.0.0.1",
                    "mysqlx=0",
                    "skip-name-resolve",
                    "no-monitor=ON",
                    "skip-log-bin",
                    "local-infile=0",
                    "secure-file-priv=NULL",
                    "innodb-buffer-pool-size=128M",
                    f"log-error={(self.root / 'logs/mysql.log').as_posix()}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        init = self.root / "private/mysql-init.sql"
        args = [f"--defaults-file={config}", "--no-monitor"]
        if not state["provisioned"]:
            init.write_text(
                f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{password}';\n"
                f"CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED BY '{password}';\n"
                "GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION;\n",
                encoding="utf-8",
            )
            args.append(f"--init-file={init}")
        try:
            record = await self.manager.start("mysql", executable, args, port)
            await asyncio.to_thread(initialize_mysql, self.root, password, rules_root, port=port)
        finally:
            await sharing_retry(lambda: init.unlink(missing_ok=True))
        state["provisioned"] = True
        self.marker.write_text(json.dumps(state), encoding="utf-8")
        return record

    async def stop(self):
        async def shutdown():
            from media_converter.storage.mysql_driver import connector

            state = json.loads(self.marker.read_text(encoding="utf-8"))
            password = self.credentials.read(state["credential_ref"])

            def request():
                with connector.connect(
                    host="127.0.0.1",
                    port=state["port"],
                    user="root",
                    password=password,
                    connection_timeout=5,
                    read_timeout=10,
                    use_pure=True,
                ) as db:
                    db.cmd_shutdown()

            await asyncio.to_thread(request)

        try:
            return await self.manager.stop("mysql", shutdown=shutdown)
        except Exception:
            # Shutdown may lose its reply as the server exits. Recheck the owned identity.
            return await self.manager.stop("mysql")
