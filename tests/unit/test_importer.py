import os
import subprocess

import pytest

from media_converter.media.importer import ImportService
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.unit


def test_recursive_duplicates_groups_and_rejections(tmp_path):
    source = tmp_path / "中文 空格"
    source.mkdir()
    (source / "同名.mp4").write_bytes(b"first")
    child = source / "child"
    child.mkdir()
    (child / "同名.mp4").write_bytes(b"second")
    output = child / "转换结果"
    output.mkdir()
    (output / "skip.mp4").write_bytes(b"output")
    with LocalStore(tmp_path / "state.sqlite3") as store:
        importer = ImportService(store)
        result = importer.import_paths([source, source / "missing.mp4"])
        assert len(result.assets) == 1 and result.rejected
        result = importer.import_paths([source], recursive=True)
        assert len(result.assets) == 1 and result.assets[0].relative_path == "child/同名.mp4"
        assert any("重复" in item.reason for item in result.rejected)
        assert store.get_import_root(result.assets[0].root_id).resolved_path == source
        single = tmp_path / "single.mp4"
        single.write_bytes(b"third")
        result = importer.import_paths([single, single])
        assert len(result.assets) == 1 and result.roots[0].kind == "single"
        hardlink = tmp_path / "alias.mp4"
        os.link(single, hardlink)
        assert not importer.import_paths([hardlink]).assets


def test_directory_link_loop_is_not_traversed(tmp_path, record_property):
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.mp4").write_bytes(b"one")
    link = source / "loop"
    try:
        link.symlink_to(source, target_is_directory=True)
        method = "symlink"
    except OSError:
        if os.name != "nt":
            pytest.skip("本机不允许创建目录链接")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(source)], capture_output=True, check=False
        )
        if result.returncode:
            pytest.skip("本机不允许创建 symlink 或 junction")
        method = "junction"
    record_property("directory_link", method)
    try:
        with LocalStore(tmp_path / "state.sqlite3") as store:
            result = ImportService(store).import_paths([source], recursive=True)
            assert len(result.assets) == 1
            assert any("目录链接" in item.reason for item in result.rejected)
    finally:
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()
