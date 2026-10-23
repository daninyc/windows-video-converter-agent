import asyncio
import csv
import errno
import hashlib
import shutil
import subprocess
import winreg
from contextlib import ExitStack, contextmanager

import pytest

from media_converter.common.errors import AppError
from media_converter.config import AppPaths, application_root
from media_converter.jobs.job_service import JobService
from media_converter.jobs.models import JobState
from media_converter.jobs.output_commit import OutputLease
from media_converter.media.importer import ImportService
from media_converter.media.models import ConversionSettings
from media_converter.media.planner import ConversionPlanner
from media_converter.media.probe import ProbeService
from media_converter.media.toolchain import inspect_toolchain
from media_converter.storage.local_store import LocalStore
from tests.integration.test_output_commit import plan_for
from tests.unit.test_conversion_planner import make_plan

pytestmark = pytest.mark.integration


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owned_test_path(path):
    assert path.resolve().is_relative_to(application_root() / "artifacts/tmp/pytest")
    return str(path)


async def plan_local(source, output, store, capabilities):
    imported = ImportService(store).import_paths([source])
    assert imported.assets, imported.rejected
    asset = await ProbeService(capabilities.ffprobe.path, store).probe(imported.assets[0])
    assert asset.probe_status == "succeeded", asset.probe_error_code
    return ConversionPlanner(capabilities).plan_one(
        ConversionSettings(output_dir=output), asset, imported.roots[0]
    )


@contextmanager
def deny_writes(output):
    identity = next(
        csv.reader(
            subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
            .strip()
            .splitlines()
        )
    )
    sid = identity[1]
    assert sid.startswith("S-1-")
    subprocess.run(
        ["icacls", owned_test_path(output), "/deny", f"*{sid}:(OI)(CI)(W)"],
        capture_output=True,
        check=True,
    )
    try:
        yield
    finally:
        subprocess.run(
            ["icacls", owned_test_path(output), "/remove:d", f"*{sid}"],
            capture_output=True,
            check=True,
        )


@pytest.mark.parametrize(
    "fault", ["readonly", "disk_full", "moved", "replaced", "commit_before", "commit_after"]
)
async def test_fault_isolated_preserves_old_result_and_next_real_conversion_succeeds(
    fault, fixture_root, tmp_path, monkeypatch, record_property
):
    source = tmp_path / "源 [特殊] # & 空格.mp4"
    shutil.copyfile(fixture_root / "media/中文 空格/基础.mp4", source)
    source_hash = digest(source)
    output = tmp_path / "fault-output"
    output.mkdir()
    capabilities = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    with LocalStore(tmp_path / "state.sqlite3") as store, ExitStack() as cleanups:
        first = await plan_local(source, output, store, capabilities)
        first.final_path.write_bytes(b"existing result must survive")
        old_hash = digest(first.final_path)
        if fault == "readonly":
            cleanups.enter_context(deny_writes(output))
            with pytest.raises(PermissionError):
                (output / "write-probe").write_bytes(b"denied")
        elif fault == "disk_full":
            acquire = OutputLease.acquire

            def no_space(lease):
                acquire(lease)
                if lease.plan.attempt_id == first.attempt_id:
                    lease.plan.temporary_path.write_bytes(b"partial before injected ENOSPC")
                    raise OSError(errno.ENOSPC, "isolated injected disk full")

            monkeypatch.setattr(OutputLease, "acquire", no_space)
        elif fault == "moved":
            source.rename(tmp_path / "moved.mp4")
        elif fault == "replaced":
            source.write_bytes(b"replacement file, must remain unchanged")
        else:
            commit = OutputLease.commit

            def interrupted_commit(lease):
                if lease.plan.attempt_id != first.attempt_id:
                    return commit(lease)
                if fault == "commit_after":
                    commit(lease)
                raise OSError(errno.EIO, "isolated injected commit interruption")

            monkeypatch.setattr(OutputLease, "commit", interrupted_commit)
        protected = tmp_path / "moved.mp4" if fault == "moved" else source
        protected_hash = digest(protected)
        second = make_plan(fixture_root, tmp_path, relative="media/无音频.mp4")
        service = JobService(store, capabilities)
        try:
            batch = await service.start_batch([first, second], f"fault-{fault}")
            results = await service.wait(batch)
            assert results[0].state == JobState.FAILED
            expected = {
                "readonly": "ACCESS_DENIED",
                "disk_full": "DISK_FULL",
                "moved": "FILE_CHANGED",
                "replaced": "FILE_CHANGED",
                "commit_before": "PROCESS_FAILED",
                "commit_after": "PROCESS_FAILED",
            }[fault]
            assert results[0].error_code == expected
            assert results[1].state == JobState.SUCCEEDED, results[1].error_code
            assert service.validations[results[1].attempt_id]["full_decode"]
            cleanups.close()
            assert digest(first.final_path) == old_hash
            assert digest(protected) == protected_hash
            assert not first.temporary_path.parent.exists()
            assert service.processor.active_count == 0
            if fault == "commit_after":
                assert results[0].output_path and service.validations.get(first.attempt_id) is None
                assert first.final_path.with_stem(first.final_path.stem + " (1)").is_file()
            else:
                assert results[0].output_path is None
            if fault != "replaced":
                assert protected_hash == source_hash
            record_property("fault", fault)
            record_property("error_code", expected)
        finally:
            await service.shutdown()


def test_output_root_replaced_with_junction_is_rejected_without_outside_writes(tmp_path):
    plan = plan_for(tmp_path)
    outside = tmp_path / "unrelated"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_bytes(b"unrelated user file")
    root = plan.output_root
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root), str(outside)],
        capture_output=True,
        check=True,
    )
    try:
        lease = OutputLease(plan)
        with pytest.raises(AppError):
            lease.acquire()
        lease.cleanup()
        assert (
            list(outside.iterdir()) == [sentinel]
            and sentinel.read_bytes() == b"unrelated user file"
        )
    finally:
        assert root.is_junction() and root.parent.resolve() == tmp_path.resolve()
        root.rmdir()


async def test_case_equivalence_and_actual_long_path_policy(
    fixture_root, tmp_path, record_property
):
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
    ) as key:
        policy, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
    record_property("windows_LongPathsEnabled", policy)
    capabilities = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    with LocalStore(tmp_path / "state.sqlite3") as store:
        short = tmp_path / "CaseVideo.mp4"
        shutil.copyfile(fixture_root / "media/超短.mp4", short)
        importer = ImportService(store)
        assert len(importer.import_paths([short, tmp_path / "casevideo.MP4"]).assets) == 1
        long_folder = tmp_path
        for i in range(4):
            long_folder /= f"长路径{i}_" + "a" * 48
        source = long_folder / "特殊 [空格] & #.mp4"
        assert len(str(source)) > 260
        try:
            long_folder.mkdir(parents=True)
            shutil.copyfile(short, source)
        except OSError as error:
            record_property("long_path_supported", False)
            record_property("long_path_winerror", error.winerror)
            assert not list(tmp_path.rglob("*.partial.mp4"))
        else:
            before = digest(source)
            plan = await plan_local(source, long_folder / "输出", store, capabilities)
            service = JobService(store, capabilities)
            batch = await service.start_batch([plan], "long-path")
            result = (await service.wait(batch))[0]
            assert result.state in {JobState.SUCCEEDED, JobState.FAILED}
            if result.state == JobState.SUCCEEDED:
                assert service.validations[result.attempt_id]["full_decode"]
            else:
                assert result.error_code and not plan.final_path.exists()
            assert digest(source) == before and not plan.temporary_path.parent.exists()
            record_property("long_path_supported", result.state == JobState.SUCCEEDED)
            record_property("source_path_characters", len(str(source)))


async def test_repeated_cancel_before_publication_preserves_source_and_next_item(
    fixture_root, tmp_path
):
    first = make_plan(fixture_root, tmp_path, relative="media/中文 空格/基础.mp4")
    second = make_plan(fixture_root, tmp_path, relative="media/无音频.mp4")
    source_hash = digest(first.source_path)
    reached = asyncio.Event()
    capabilities = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    from media_converter.jobs.output_validator import OutputValidator

    class PausedValidator(OutputValidator):
        async def validate(self, plan):
            result = await super().validate(plan)
            if plan.attempt_id == first.attempt_id:
                reached.set()
                await asyncio.Event().wait()
            return result

    with LocalStore(tmp_path / "state.sqlite3") as store:
        service = JobService(store, capabilities, validator=PausedValidator(capabilities))
        try:
            batch = await service.start_batch([first, second], "repeat-cancel")
            await asyncio.wait_for(reached.wait(), 30)
            assert await service.cancel_current(batch)
            assert await service.cancel_current(batch)
            results = await service.wait(batch)
            assert [r.state for r in results] == [JobState.CANCELLED, JobState.SUCCEEDED]
            assert not first.final_path.exists() and not first.temporary_path.parent.exists()
            assert digest(first.source_path) == source_hash
            assert not await service.cancel_current(batch)
            assert not await service.cancel_batch(batch)
        finally:
            await service.shutdown()
