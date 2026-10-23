import asyncio
import hashlib
import stat
import zipfile

import pytest

from media_converter.common.errors import AppError
from media_converter.common.windows_files import filesystem_path
from media_converter.services.component_manifest import Artifact, file_matches, relative_name
from media_converter.services.downloads import Downloader, safe_extract


@pytest.mark.parametrize("name", ["../escape", "C:/escape", "a:ads", "a/CON.txt", "a/a.", "a/../b"])
def test_bad_names(name):
    with pytest.raises(AppError):
        relative_name(name)


@pytest.mark.parametrize("mode", ["escape", "link", "limit", "case"])
def test_extract_rejects_unsafe(tmp_path, mode):
    archive, target = tmp_path / "input.zip", tmp_path / "stage"
    with zipfile.ZipFile(archive, "w") as zip:
        if mode == "escape":
            zip.writestr("../secret", "data")
        elif mode == "link":
            item = zipfile.ZipInfo("link")
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            zip.writestr(item, "../secret")
        elif mode == "case":
            zip.writestr("A", "a")
            zip.writestr("a", "b")
        else:
            zip.writestr("large", b"a" * 200)
    with pytest.raises(AppError):
        safe_extract(archive, target, limit=100)
    assert not target.exists() and not (tmp_path / "secret").exists()


def test_git_blob_and_sha_integrity(tmp_path):
    file = tmp_path / "model"
    file.write_bytes(b"hello")
    item = Artifact(
        "model",
        "1",
        "https://example.org/model",
        hashlib.sha1(b"blob 5\0hello").hexdigest(),
        5,
        "model",
        "MIT",
        "git-blob-sha1",
    )
    assert file_matches(file, item)
    file.write_bytes(b"wrong")
    assert not file_matches(file, item)


def test_cancelled_extraction_cleans_only_its_new_staging_directory(tmp_path):
    archive = tmp_path / "component.zip"
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr("a", b"some-data")
    protected = tmp_path / "other-file"
    protected.write_text("keep")
    with pytest.raises(asyncio.CancelledError):
        safe_extract(archive, tmp_path / "stage", limit=100, cancel=lambda: True)
    assert protected.read_text() == "keep" and not (tmp_path / "stage").exists()


async def test_long_component_notice_paths_install_verify_and_reuse(tmp_path):
    import hashlib

    archive = tmp_path / "notices.zip"
    member = "a" * 80 + "/" + "b" * 80 + "/LICENSE"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(member, "upstream notice")
    item = Artifact(
        "notices",
        "1",
        "",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        archive.stat().st_size,
        "notices",
        "fixture",
        archive=True,
        expanded_limit=100,
        adjacent_only=True,
    )
    downloader = Downloader(tmp_path)
    installed = await downloader.install(item, cached=archive)
    assert len(str(installed / member)) > 260
    assert filesystem_path(installed / member).read_text() == "upstream notice"
    assert await downloader.install(item, cached=archive) == installed
