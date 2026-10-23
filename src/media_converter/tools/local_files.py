import asyncio
import json
import os

from media_converter.common.errors import AppError, ErrorCode
from media_converter.common.process import terminate_owned


class LocalFiles:
    def __init__(self, reader_path=None):
        self.reader_path = str(reader_path) if reader_path else None
        self.slots = asyncio.Semaphore(2)
        self.processes = set()

    async def read(self, arguments, context):
        reference = next(
            (
                r
                for r in context.references
                if r.reference_id == arguments.file_ref_id and r.kind == "file"
            ),
            None,
        )
        if reference is None:
            raise AppError(ErrorCode.ACCESS_DENIED)
        async with self.slots:
            from media_converter.worker_runtime import worker_command

            process = await asyncio.create_subprocess_exec(
                *worker_command("document"),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            self.processes.add(process)
            try:
                payload = json.dumps(
                    {
                        "reference": reference.model_dump(mode="json"),
                        "arguments": arguments.model_dump(),
                        "reader_path": self.reader_path,
                        "turn_id": context.turn_id,
                    }
                ).encode()
                async with asyncio.timeout(30):
                    await process.stdin.drain()
                    process.stdin.write(payload)
                    await process.stdin.drain()
                    process.stdin.close()
                    data = await process.stdout.read(300000)
                    if len(data) >= 300000:
                        raise AppError(ErrorCode.FILE_TOO_LARGE)
                    await process.wait()
                result = json.loads(data)
                if process.returncode or not result["ok"]:
                    raise AppError(ErrorCode(result.get("error_code", "PROCESS_FAILED")))
                return result["data"]
            except TimeoutError as error:
                raise AppError(ErrorCode.TIMEOUT) from error
            finally:
                await terminate_owned(process)
                self.processes.discard(process)

    async def close(self):
        await asyncio.gather(*(terminate_owned(p) for p in self.processes))
