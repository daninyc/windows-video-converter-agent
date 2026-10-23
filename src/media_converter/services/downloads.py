import asyncio
import errno
import json
import os
import shutil
import stat
import zipfile
from pathlib import Path
from uuid import uuid4

from media_converter.common.errors import AppError, ErrorCode
from media_converter.common.windows_files import filesystem_path, sharing_retry
from media_converter.services.component_manifest import file_matches, relative_name


def sha256_file(path):
    import hashlib

    with filesystem_path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_cancel(cancel):
    if cancel():
        raise asyncio.CancelledError


async def await_worker(function, *args, **kwargs):
    # Cancellation must wait for the writer to close its handles before removing its staging path.
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


def safe_extract(archive, destination, *, limit, cancel=lambda: False):
    """Extract only regular files into a new private staging directory."""
    destination = Path(destination).resolve()
    filesystem_path(destination).mkdir(parents=True, exist_ok=False)
    seen, total = set(), 0
    try:
        with zipfile.ZipFile(archive) as source:
            if len(source.infolist()) > 30000:
                raise AppError(ErrorCode.FILE_TOO_LARGE)
            for entry in source.infolist():
                check_cancel(cancel)
                name = relative_name(entry.filename)
                mode = entry.external_attr >> 16
                if (
                    stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                    or entry.flag_bits & 1
                    or name.casefold() in seen
                ):
                    raise AppError(ErrorCode.ACCESS_DENIED)
                seen.add(name.casefold())
                target = destination / name
                if not target.resolve().is_relative_to(destination):
                    raise AppError(ErrorCode.ACCESS_DENIED)
                total += entry.file_size
                if total > limit:
                    raise AppError(ErrorCode.FILE_TOO_LARGE)
                if entry.is_dir():
                    filesystem_path(target).mkdir(parents=True, exist_ok=True)
                    continue
                filesystem_path(target.parent).mkdir(parents=True, exist_ok=True)
                with source.open(entry) as reader, filesystem_path(target).open("xb") as writer:
                    while block := reader.read(1024 * 1024):
                        check_cancel(cancel)
                        writer.write(block)
        return total
    except BaseException:
        # This directory was created by this call and is verified inside its chosen parent.
        shutil.rmtree(filesystem_path(destination))
        raise


class Downloader:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()
        self.cache = self.root / "downloads"
        self.cache.mkdir(parents=True, exist_ok=True)
        if not self.cache.resolve().is_relative_to(self.root):
            raise AppError(ErrorCode.ACCESS_DENIED)

    async def obtain(self, artifact, *, cached=None, cancel=lambda: False, emit=lambda v: None):
        check_cancel(cancel)
        final = self.cache / (artifact.name + "-" + artifact.digest)
        for path in (final, cached):
            if path and await asyncio.to_thread(file_matches, path, artifact):
                emit({"component": artifact.name, "state": "reused", "bytes": artifact.size})
                return Path(path)
        if artifact.adjacent_only:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        partial, meta = Path(str(final) + ".partial"), Path(str(final) + ".json")
        if any(not p.resolve().is_relative_to(self.root) for p in (final, partial, meta)):
            raise AppError(ErrorCode.ACCESS_DENIED)
        offset = partial.stat().st_size if partial.exists() else 0
        if offset >= artifact.size:
            partial.unlink()
            offset = 0
        headers = {"Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
            if meta.exists():
                etag = json.loads(meta.read_text("utf-8")).get("etag")
                if etag:
                    headers["If-Range"] = etag
        try:
            import httpx
        except ImportError as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                async with client.stream("GET", artifact.url, headers=headers) as response:
                    if response.status_code not in {200, 206}:
                        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
                    if response.status_code == 206:
                        expected = f"bytes {offset}-{artifact.size - 1}/{artifact.size}"
                        if response.headers.get("Content-Range") != expected:
                            raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                    else:
                        offset = 0
                    meta.write_text(json.dumps({"etag": response.headers.get("etag")}), "utf-8")
                    with partial.open("ab" if offset else "wb") as stream:
                        async for block in response.aiter_bytes(256 * 1024):
                            check_cancel(cancel)
                            offset += len(block)
                            if offset > artifact.size:
                                raise AppError(ErrorCode.FILE_TOO_LARGE)
                            stream.write(block)
                            emit(
                                {
                                    "component": artifact.name,
                                    "state": "downloading",
                                    "bytes": offset,
                                    "total": artifact.size,
                                }
                            )
            check_cancel(cancel)
            emit({"component": artifact.name, "state": "verifying"})
            if not await asyncio.to_thread(file_matches, partial, artifact):
                partial.unlink(missing_ok=True)
                raise AppError(ErrorCode.OUTPUT_INVALID)
            check_cancel(cancel)
            os.replace(partial, final)
            meta.unlink(missing_ok=True)
            return final
        except httpx.HTTPError as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error

    async def install(self, artifact, *, cached=None, cancel=lambda: False, emit=lambda v: None):
        try:
            return await self._install(artifact, cached=cached, cancel=cancel, emit=emit)
        except OSError as error:
            code = (
                ErrorCode.DISK_FULL
                if error.errno == errno.ENOSPC or getattr(error, "winerror", None) == 112
                else ErrorCode.ACCESS_DENIED
            )
            raise AppError(code) from error

    async def _install(self, artifact, *, cached=None, cancel=lambda: False, emit=lambda v: None):
        target = self.root / "components" / relative_name(artifact.destination)
        if not target.resolve().is_relative_to(self.root):
            raise AppError(ErrorCode.ACCESS_DENIED)
        marker = self.root / "components/installed" / (artifact.name + ".json")
        if not marker.resolve().is_relative_to(self.root):
            raise AppError(ErrorCode.ACCESS_DENIED)
        if marker.exists():
            data = json.loads(marker.read_text("utf-8"))
            if data["digest"] == artifact.digest:
                valid = bool(data.get("files")) and target.exists()
                for name, digest in data["files"].items():
                    path = target / relative_name(name) if artifact.archive else target
                    if (
                        not filesystem_path(path).is_file()
                        or await asyncio.to_thread(sha256_file, path) != digest
                    ):
                        valid = False
                        break
                if valid:
                    return target
        if target.exists():
            # Never overwrite unmarked or damaged installations while a service may use them.
            raise AppError(ErrorCode.FILE_CHANGED)
        source = await self.obtain(artifact, cached=cached, cancel=cancel, emit=emit)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / (".stage-" + uuid4().hex)
        try:
            emit({"component": artifact.name, "state": "installing"})
            if artifact.archive:
                await await_worker(
                    safe_extract, source, stage, limit=artifact.expanded_limit, cancel=cancel
                )
            else:
                await await_worker(shutil.copyfile, source, stage)
            check_cancel(cancel)
            import hashlib

            def hashes():
                scan = filesystem_path(stage)
                files = list(scan.rglob("*")) if artifact.archive else [scan]
                result = {}
                for file in files:
                    if file.is_file():
                        with file.open("rb") as stream:
                            result[
                                file.relative_to(scan).as_posix() if artifact.archive else "."
                            ] = hashlib.file_digest(stream, "sha256").hexdigest()
                return result

            value = {
                "version": artifact.version,
                "digest": artifact.digest,
                "license": artifact.license,
                "source": artifact.url,
                "files": await await_worker(hashes),
            }
            marker.parent.mkdir(parents=True, exist_ok=True)
            pending_marker = marker.with_suffix("." + uuid4().hex + ".partial")
            try:
                pending_marker.write_text(json.dumps(value, indent=2), "utf-8")
                os.replace(pending_marker, marker)
            finally:
                pending_marker.unlink(missing_ok=True)
            check_cancel(cancel)
            # On Windows rename fails if a target appeared; never replace a foreign installation.
            await sharing_retry(lambda: os.rename(stage, target))
            return target
        finally:
            if stage.exists():
                if stage.is_dir():
                    shutil.rmtree(filesystem_path(stage))
                else:
                    stage.unlink()
