import os
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from media_converter.media.models import FileFingerprint, ImportRoot, MediaAsset
from media_converter.storage.local_store import LocalStore

VIDEO_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm",
        ".m4v",
        ".ts",
        ".mts",
        ".m2ts",
        ".wmv",
        ".flv",
        ".3gp",
        ".mpeg",
        ".mpg",
        ".y4m",
    }
)


@dataclass(frozen=True)
class ImportRejection:
    path: str
    reason: str


@dataclass(frozen=True)
class ImportResult:
    assets: tuple[MediaAsset, ...]
    roots: tuple[ImportRoot, ...]
    rejected: tuple[ImportRejection, ...]


class ImportService:
    def __init__(self, store: LocalStore, excluded_directories=()):
        self.store = store
        self.excluded_directories = {Path(p).resolve() for p in excluded_directories}
        self._lock = threading.Lock()

    def import_paths(self, paths, recursive: bool = False) -> ImportResult:
        assets, roots, rejected = [], {}, []
        with self._lock:
            existing = self.store.list_assets()
            identities = {asset.fingerprint.file_identity for asset in existing}
            resolved_names = {os.path.normcase(str(asset.resolved_path)) for asset in existing}
            visited = set()

            def reject(path, reason):
                rejected.append(ImportRejection(str(path), reason))

            def excluded(path):
                return (
                    path.name == "转换结果"
                    or path.name.startswith(".media-converter-")
                    or any(
                        path == base or path.is_relative_to(base)
                        for base in self.excluded_directories
                    )
                )

            def add(path, root, explicit=False):
                try:
                    resolved = path.resolve(strict=True)
                    if resolved.suffix.lower() not in VIDEO_EXTENSIONS or not resolved.is_file():
                        reject(path, "不是支持的视频文件")
                        return
                    if not explicit and excluded(resolved.parent):
                        reject(path, "已跳过应用输出目录")
                        return
                    fingerprint = FileFingerprint.from_path(resolved)
                    normalized = os.path.normcase(str(resolved))
                    if fingerprint.file_identity in identities or normalized in resolved_names:
                        reject(path, "重复文件")
                        return
                    # An external file link keeps a separate source root.
                    if not resolved.is_relative_to(root.resolved_path):
                        root = make_root(resolved.parent, "single")
                    asset = MediaAsset(
                        root_id=root.root_id,
                        relative_path=resolved.relative_to(root.resolved_path).as_posix(),
                        resolved_path=resolved,
                        fingerprint=fingerprint,
                    )
                    if root.root_id not in roots:
                        self.store.save_import_root(root)
                        roots[root.root_id] = root
                    self.store.save_asset(asset)
                    assets.append(asset)
                    identities.add(fingerprint.file_identity)
                    resolved_names.add(normalized)
                except (OSError, ValueError):
                    reject(path, "文件不存在、无法读取或路径无效")

            def make_root(directory, kind):
                root_id = str(uuid5(NAMESPACE_URL, kind + ":" + os.path.normcase(str(directory))))
                return ImportRoot(
                    root_id=root_id,
                    resolved_path=directory,
                    display_group="单独添加" if kind == "single" else directory.name,
                    recursive=recursive if kind == "directory" else False,
                    kind=kind,
                )

            def scan(directory, root):
                try:
                    if directory.is_symlink() or directory.is_junction():
                        reject(directory, "已跳过目录链接")
                        return
                    if excluded(directory.resolve()):
                        reject(directory, "已跳过应用输出目录")
                        return
                    identity = FileFingerprint.from_path(directory).file_identity
                    if identity in visited:
                        reject(directory, "已扫描此目录")
                        return
                    visited.add(identity)
                    with os.scandir(directory) as entries:
                        children = sorted(entries, key=lambda entry: entry.name.casefold())
                    for entry in children:
                        child = Path(entry.path)
                        if child.is_dir():
                            if child.is_symlink() or child.is_junction():
                                reject(child, "已跳过目录链接")
                            elif recursive:
                                scan(child, root)
                        elif child.suffix.lower() in VIDEO_EXTENSIONS:
                            add(child, root)
                except OSError:
                    reject(directory, "目录无法读取")

            for value in paths:
                path = Path(value)
                try:
                    if path.is_dir():
                        if path.is_symlink() or path.is_junction():
                            reject(path, "已跳过目录链接")
                        else:
                            resolved = path.resolve(strict=True)
                            scan(resolved, make_root(resolved, "directory"))
                    else:
                        resolved = path.resolve(strict=True)
                        add(resolved, make_root(resolved.parent, "single"), explicit=True)
                except (OSError, ValueError):
                    reject(path, "路径不存在或无法访问")
        return ImportResult(tuple(assets), tuple(roots.values()), tuple(rejected))
