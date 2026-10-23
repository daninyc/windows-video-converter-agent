import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from media_converter.common.errors import AppError, ErrorCode
from media_converter.storage.mysql_sync import mysql_config


class MySQLQueries:
    def __init__(self, data_dir, reader):
        self.data_dir, self.reader = data_dir, reader
        self.pool = None
        self.pool_lock = __import__("threading").Lock()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mysql-query")
        self.slots = asyncio.Semaphore(4)

    def _borrow(self):
        from media_converter.storage.mysql_driver import connector

        MySQLConnectionPool = connector.pooling.MySQLConnectionPool

        with self.pool_lock:
            if self.pool is None:
                self.pool = MySQLConnectionPool(
                    pool_size=4, pool_reset_session=True, **mysql_config(self.data_dir, "reader")
                )
        return self.pool.get_connection()

    def _query(self, name, arguments, context):
        connection = self._borrow()
        cursor = None
        try:
            cursor = connection.cursor(dictionary=True)
            parameters = []
            if name == "lookup_technical_rules":
                sql = "SELECT rule_id,version,source_ref,rule_json FROM technical_rules WHERE 1=1"
                for field, column in (
                    ("rule_kind", "rule_kind"),
                    ("format", "format_name"),
                    ("codec", "codec"),
                    ("error_code", "error_code"),
                ):
                    value = getattr(arguments, field)
                    if value is not None:
                        sql += f" AND {column}=%s"
                        parameters.append(value)
                key = "rules"
            elif name == "list_conversion_presets":
                sql = (
                    "SELECT preset_id,version,name,container,settings_json FROM presets "
                    "WHERE instance_id IN (%s,'builtin')"
                )
                parameters.append(context.instance_id)
                for field, column in (("preset_name", "name"), ("container", "container")):
                    value = getattr(arguments, field)
                    if value is not None:
                        sql += f" AND {column}=%s"
                        parameters.append(value)
                key = "presets"
            else:
                sql = (
                    "SELECT attempt_id,asset_id,status,version,payload,updated_at "
                    "FROM conversion_attempts WHERE instance_id=%s"
                )
                parameters.append(context.instance_id)
                for field, column in (("task_id", "attempt_id"), ("status", "status")):
                    value = getattr(arguments, field)
                    if value is not None:
                        sql += f" AND {column}=%s"
                        parameters.append(value)
                for field, operator in (("since", ">="), ("until", "<=")):
                    value = getattr(arguments, field)
                    if value is not None:
                        try:
                            datetime.fromisoformat(value)
                        except ValueError as error:
                            raise AppError(ErrorCode.INVALID_ARGUMENT) from error
                        sql += f" AND updated_at{operator}%s"
                        parameters.append(value)
                sql += " ORDER BY updated_at DESC"
                key = "attempts"
            sql += " LIMIT %s"
            parameters.append(arguments.limit)
            cursor.execute(sql, tuple(parameters))
            rows = cursor.fetchall()
            for row in rows:
                for field in ("source_ref", "rule_json", "settings_json", "payload"):
                    if field in row and isinstance(row[field], str):
                        row[field] = json.loads(row[field])
                if "settings_json" in row:
                    row["settings_json"].pop("output_dir", None)
            cursor.execute(
                "SELECT watermark,data_time FROM sync_state WHERE instance_id=%s",
                (context.instance_id,),
            )
            water = cursor.fetchone() or {"watermark": 0, "data_time": None}
            pending = self.reader._rows(
                "SELECT COUNT(*) FROM outbox_events WHERE synced_at IS NULL"
            )[0][0]
            return {
                key: rows,
                "freshness": {**water, "pending_events": pending, "stale": pending > 0},
                "sources": [row["source_ref"] for row in rows if "source_ref" in row],
            }
        finally:
            if cursor:
                cursor.close()
            connection.close()

    async def query(self, name, arguments, context):
        await self.slots.acquire()
        future = asyncio.get_running_loop().run_in_executor(
            self.executor, self._query, name, arguments, context
        )

        def completed(task):
            self.slots.release()
            if not task.cancelled():
                task.exception()

        future.add_done_callback(completed)
        try:
            async with asyncio.timeout(10):
                return await asyncio.shield(future)
        except TimeoutError as error:
            raise AppError(ErrorCode.TIMEOUT) from error
        except AppError:
            raise
        except Exception as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error

    async def close(self):
        await asyncio.to_thread(self.executor.shutdown, True, cancel_futures=True)
