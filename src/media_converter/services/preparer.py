"""Shared CLI/desktop preparation; UI lifetime does not own preparation lifetime."""

import asyncio
import importlib.util
import json
import shutil
import socket
import sys
from pathlib import Path

from media_converter.common.errors import AppError, ErrorCode
from media_converter.config import AppPaths, application_root
from media_converter.services.component_manifest import inventory
from media_converter.services.downloads import Downloader, check_cancel
from media_converter.services.health import HealthService
from media_converter.services.mysql_instance import MySQLInstance
from media_converter.services.process_manager import ProcessManager


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class SetupService:
    def __init__(self, data_dir, *, environment_root=None, health=None):
        self.root = Path(data_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.environment = (
            Path(environment_root) if environment_root else application_root() / "environment"
        )
        self.health = health or HealthService(self.root)
        self.manager = ProcessManager(self.root)
        self.mysql = MySQLInstance(self.root, self.manager)
        self.lock = asyncio.Lock()
        self.current = None
        self.cancelled = False
        self.report = None
        self.history = []

    def event(self, value, emit):
        self.history.append(value)
        self.history = self.history[-100:]
        emit(value)

    def cancel(self):
        if self.cancelled:
            return
        self.cancelled = True
        if self.current:
            self.current.cancel()

    def plan(self):
        from media_converter.worker_runtime import installed_worker

        artifacts = inventory()
        remaining = []
        for artifact in artifacts:
            marker = self.root / "components/installed" / (artifact.name + ".json")
            try:
                installed = json.loads(marker.read_text("utf-8"))["digest"] == artifact.digest
                installed &= (self.root / "components" / artifact.destination).exists()
            except (OSError, ValueError, KeyError):
                installed = False
            if not installed:
                remaining.append(artifact)
        return {
            "download_bytes": sum(a.size for a in artifacts),
            "space_bytes": sum(
                a.size + (a.expanded_limit if a.archive else a.size) for a in artifacts
            ),
            "free_bytes": shutil.disk_usage(self.root).free,
            "required_bytes": sum(
                a.size + (a.expanded_limit if a.archive else a.size) for a in remaining
            )
            + 64 * 1024**2,
            "sources": sorted({a.url.split("/")[2] for a in artifacts}),
            "artifacts": [
                {
                    "name": a.name,
                    "version": a.version,
                    "source": a.url,
                    "bytes": a.size,
                    "license": a.license,
                }
                for a in artifacts
            ],
            "worker_available": bool(installed_worker(self.root))
            if getattr(sys, "frozen", False)
            else all(
                importlib.util.find_spec(name) is not None
                for name in ("mcp", "sentence_transformers", "qdrant_client")
            ),
            "worker_note": "此版本尚未附带独立 AI 运行组件；请使用完整组件包，或继续使用视频转换。",
        }

    async def inspect(self, emit=lambda v: None):
        owns_task = self.current is None
        if owns_task:
            self.current, self.cancelled = asyncio.current_task(), False
            self.manager.notify = lambda value: self.event(value, emit)
        try:
            self.report = await self.health.inspect(emit=lambda v: self.event(v, emit))
            return self.report
        finally:
            if owns_task:
                self.current = None

    async def prepare(self, *, mode="reuse", emit=lambda v: None, components="ai"):
        from PySide6.QtCore import QLockFile

        if self.lock.locked():
            raise AppError(ErrorCode.INVALID_STATE)
        async with self.lock:
            lease = QLockFile(str(self.root / "prepare.lock"))
            if not lease.tryLock(0):
                raise AppError(ErrorCode.INVALID_STATE)
            self.current, self.cancelled = asyncio.current_task(), False
            try:
                self.manager.notify = lambda value: self.event(value, emit)
                if components == "core":
                    return await self._core(emit)
                if mode not in {"reuse", "private"}:
                    raise AppError(ErrorCode.INVALID_ARGUMENT)
                self.event({"component": "environment", "state": "checking"}, emit)
                if not self.plan()["worker_available"] and getattr(sys, "frozen", False):
                    await self.prepare_worker(emit)
                if not self.plan()["worker_available"]:
                    self.event(
                        {
                            "component": "ai-worker",
                            "state": "missing",
                            "message": self.plan()["worker_note"],
                        },
                        emit,
                    )
                    raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
                # Reusing a private installation still requires restoring its stopped services.
                if mode == "private" or (self.root / "private-components.json").exists():
                    await self._private(emit)
                else:
                    if not (self.root / "ai-components.json").exists():
                        from media_converter.devtools.agent_setup import configure_ai

                        await configure_ai(self.root, self.environment)
                    if not (self.root / "mysql.json").exists():
                        self.event(
                            {
                                "component": "mysql",
                                "state": "missing",
                                "message": "没有可复用的项目数据库配置；请选择准备私有组件。",
                            },
                            emit,
                        )
                        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
                check_cancel(lambda: self.cancelled)
                self.event({"component": "knowledge", "state": "indexing"}, emit)
                from media_converter.worker_runtime import build_index

                await build_index(self.root, application_root() / "knowledge")
                result = await self.inspect(emit)
                if not result["ok"]:
                    raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
                return result
            except BaseException:
                await self.stop_owned()
                raise
            finally:
                self.current = None
                lease.unlock()

    async def prepare_worker(self, emit):
        from media_converter.services.component_manifest import Artifact

        manifest = application_root() / "MediaConverter-AI-manifest.json"
        if not manifest.is_file():
            return
        item = Artifact(**json.loads(manifest.read_text("utf-8"))["artifact"])
        adjacent = application_root() / "MediaConverter-AI-Windows-x64.zip"
        await Downloader(self.root).install(
            item, cached=adjacent, cancel=lambda: self.cancelled, emit=lambda v: self.event(v, emit)
        )

    async def _core(self, emit):
        from media_converter.media.toolchain import inspect_toolchain

        try:
            snapshot = await asyncio.to_thread(inspect_toolchain, AppPaths(self.root))
            snapshot.require_ready()
        except AppError:
            item = next(a for a in inventory() if a.name == "ffmpeg")
            folder = await Downloader(self.root).install(
                item,
                cached=self.environment / "downloads/ffmpeg.zip",
                cancel=lambda: self.cancelled,
                emit=emit,
            )
            bins = {name: str(next(folder.rglob(name + ".exe"))) for name in ("ffmpeg", "ffprobe")}
            (self.root / "toolchain.json").write_text(json.dumps(bins), "utf-8")
        return await self.health.inspect(require="core", emit=emit)

    async def _private(self, emit):
        # Existing external configuration is never silently replaced.
        configuration = self.root / "private-components.json"
        if not configuration.exists() and any(
            (self.root / p).exists() for p in ("ai-components.json", "mysql.json")
        ):
            self.event(
                {
                    "component": "environment",
                    "state": "blocked",
                    "message": "当前目录已有外部组件配置，请选择复用方式。",
                    "action": "如需私有组件，请使用新的数据目录启动应用。",
                },
                emit,
            )
            raise AppError(ErrorCode.ACCESS_DENIED)
        if self.plan()["free_bytes"] < self.plan()["required_bytes"]:
            raise AppError(ErrorCode.DISK_FULL)
        downloader, installed = Downloader(self.root), {}
        for item in inventory():
            if item.name == "ffmpeg":
                continue
            cache = (
                self.environment / "downloads" / (item.name + ".zip")
                if item.archive
                else (self.environment / item.destination)
            )
            installed[item.name] = await downloader.install(
                item,
                cached=cache,
                cancel=lambda: self.cancelled,
                emit=lambda v: self.event(v, emit),
            )
        check_cancel(lambda: self.cancelled)
        model_manifest = json.loads(Path(__file__).with_name("components.json").read_text("utf-8"))
        manifest = (
            self.root
            / "components/models/ollama/manifests/registry.ollama.ai/library/bge-m3/latest"
        )
        manifest.parent.mkdir(parents=True, exist_ok=True)
        # Preserve the exact byte representation: Ollama's model digest hashes these bytes.
        source_manifest = (
            self.environment / "models/ollama/manifests/registry.ollama.ai/library/bge-m3/latest"
        )
        if source_manifest.exists():
            content = source_manifest.read_bytes()
        else:
            content = model_manifest["embedding_manifest_text"].encode()
        import hashlib

        expected = next(a.version for a in inventory() if a.name.startswith("bge-"))
        if hashlib.sha256(content).hexdigest() != expected:
            raise AppError(ErrorCode.OUTPUT_INVALID)
        manifest.write_bytes(content)
        state = (
            json.loads(configuration.read_text("utf-8"))
            if configuration.exists()
            else {"ollama_port": free_port(), "qdrant_port": free_port(), "mysql_port": free_port()}
        )
        configuration.write_text(json.dumps(state), "utf-8")
        profile = self.root / "components/profile"
        profile.mkdir(exist_ok=True)
        env = {
            "USERPROFILE": str(profile),
            "HOME": str(profile),
            "LOCALAPPDATA": str(profile / "local"),
            "APPDATA": str(profile / "roaming"),
            "OLLAMA_MODELS": str(self.root / "components/models/ollama"),
            "OLLAMA_HOST": f"127.0.0.1:{state['ollama_port']}",
            "OLLAMA_NO_CLOUD": "1",
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_MAX_QUEUE": "32",
        }
        self.event({"component": "services", "state": "starting"}, emit)
        await self.manager.start(
            "ollama",
            next(installed["ollama"].rglob("ollama.exe")),
            ["serve"],
            state["ollama_port"],
            environment=env,
        )
        # Qdrant's distributed binary only enables the YAML config loader. JSON is YAML-compatible.
        qconfig = self.root / "components/qdrant.yaml"
        qconfig.write_text(
            json.dumps(
                {
                    "storage": {"storage_path": str(self.root / "components/qdrant-data")},
                    "service": {
                        "host": "127.0.0.1",
                        "http_port": state["qdrant_port"],
                        "grpc_port": None,
                    },
                    "telemetry_disabled": True,
                }
            ),
            "utf-8",
        )
        await self.manager.start(
            "qdrant",
            next(installed["qdrant"].rglob("qdrant.exe")),
            ["--config-path", str(qconfig), "--disable-telemetry"],
            state["qdrant_port"],
        )
        marker = self.root / "private/mysql-instance.json"
        # An already initialized private database keeps its original engine; no implicit upgrade.
        mysql_path = (
            json.loads(marker.read_text("utf-8"))["executable"]
            if marker.exists()
            else str(next(installed["mysql"].rglob("mysqld.exe")))
        )
        await self.mysql.prepare(mysql_path, state["mysql_port"], application_root() / "knowledge")
        check_cancel(lambda: self.cancelled)
        from media_converter.rag.embedding import EmbeddingService

        url = f"http://127.0.0.1:{state['ollama_port']}"
        self.event({"component": "models", "state": "warming"}, emit)
        identity = await EmbeddingService(url).identity()
        files = [
            {
                "file": a.destination.rsplit("/", 1)[-1],
                "bytes": a.size,
                "algorithm": a.algorithm,
                "digest": a.digest,
            }
            for a in inventory()
            if a.name.startswith("reranker-")
        ]
        config = {
            "schema_version": 1,
            "ollama_url": url,
            "qdrant_url": f"http://127.0.0.1:{state['qdrant_port']}",
            "embedding_model": identity["model"],
            "embedding_digest": identity["digest"],
            "reranker_path": str(self.root / "components/models/reranker"),
            "reranker_revision": next(
                a.version for a in inventory() if a.name.startswith("reranker-")
            ),
            "reranker_files": files,
            "relevance_threshold": 0.5,
        }
        (self.root / "ai-components.json").write_text(json.dumps(config), "utf-8")

    async def stop_owned(self):
        for name in ("mysql", "qdrant", "ollama"):
            if await asyncio.to_thread(self.manager.inspect, name):
                if name == "mysql":
                    await self.mysql.stop()
                else:
                    await self.manager.stop(name)

    async def close(self):
        self.cancel()
        current = self.current
        if current and current is not asyncio.current_task():
            await asyncio.gather(current, return_exceptions=True)
        await self.stop_owned()
