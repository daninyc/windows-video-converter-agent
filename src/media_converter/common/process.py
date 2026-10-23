import asyncio
import os

from media_converter.common.errors import AppError, ErrorCode


async def terminate_owned(process):
    if process.returncode is not None:
        return
    try:
        process.terminate()
        await asyncio.wait_for(process.wait(), 1)
    except TimeoutError:
        process.kill()
        await process.wait()
    except ProcessLookupError:
        pass


async def capture_process(
    binary, arguments, *, timeout=15, max_stdout=16 * 1024 * 1024, environment=None
):
    try:
        process = await asyncio.create_subprocess_exec(
            str(binary),
            *map(str, arguments),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=0x08000000 if os.name == "nt" else 0,
            env={**os.environ, **environment} if environment else None,
        )
    except OSError as error:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error

    async def read(stream, limit, *, tail=False):
        output = bytearray()
        while chunk := await stream.read(16384):
            output.extend(chunk)
            if len(output) > limit:
                if not tail:
                    raise AppError(ErrorCode.FILE_TOO_LARGE)
                del output[:-limit]
        return bytes(output)

    readers = [
        asyncio.create_task(read(process.stdout, max_stdout)),
        asyncio.create_task(read(process.stderr, 65536, tail=True)),
    ]
    try:
        async with asyncio.timeout(timeout):
            stdout, _ = await asyncio.gather(*readers)
            code = await process.wait()
        if code:
            raise AppError(ErrorCode.PROCESS_FAILED)
        return stdout
    except TimeoutError as error:
        raise AppError(ErrorCode.TIMEOUT) from error
    finally:
        if process.returncode is None:
            await terminate_owned(process)
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
