import asyncio
from types import SimpleNamespace

import pytest

from media_converter.common.errors import AppError, ErrorCode
from media_converter.config import AppPaths
from media_converter.jobs.job_service import JobService
from media_converter.jobs.models import JobState
from media_converter.media.toolchain import inspect_toolchain
from media_converter.storage.local_store import LocalStore
from tests.unit.test_conversion_planner import make_plan

pytestmark = pytest.mark.unit


class FakeProcessor:
    def __init__(self):
        self.calls = []

    async def run(self, plan, cancel, callback, **kwargs):
        self.calls.append(plan.attempt_id)
        plan.temporary_path.write_bytes(b"isolated test output")
        await asyncio.sleep(0)
        return SimpleNamespace(exit_code=0, cancelled=False)


async def test_batch_dedup_snapshot_validation_failure_and_continue(fixture_root, tmp_path):
    first = make_plan(fixture_root, tmp_path, relative="media/中文 空格/基础.mp4")
    second = make_plan(fixture_root, tmp_path, relative="media/无音频.mp4")

    class Validator:
        async def validate(self, plan):
            if plan.plan_id == first.plan_id:
                raise AppError(ErrorCode.OUTPUT_INVALID)
            return {"unit_test_double": True}

    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    with LocalStore(tmp_path / "state.sqlite3") as store:
        processor = FakeProcessor()
        service = JobService(store, snapshot, processor=processor, validator=Validator())
        batch = await service.start_batch([first, second], "same-command")
        assert await service.start_batch([first, second], "same-command") == batch
        result = await service.wait(batch)
        assert [item.state for item in result] == [JobState.FAILED, JobState.SUCCEEDED]
        assert result[0].error_code == "OUTPUT_INVALID" and len(processor.calls) == 2
        assert store.get_plan(first.plan_id).settings_snapshot == first.settings_snapshot
        assert not first.final_path.exists()


async def test_published_result_survives_terminal_store_failure(
    fixture_root, tmp_path, monkeypatch
):
    plan = make_plan(fixture_root, tmp_path, relative="media/无音频.mp4")

    class Validator:
        async def validate(self, plan):
            return {"test_double": True}

    with LocalStore(tmp_path / "state.sqlite3") as store:
        original = store.save_attempt

        def fail_success(attempt):
            if attempt.state == JobState.SUCCEEDED:
                raise OSError("injected write failure")
            return original(attempt)

        monkeypatch.setattr(store, "save_attempt", fail_success)
        service = JobService(
            store,
            inspect_toolchain(AppPaths.from_argument(tmp_path / "data")),
            processor=FakeProcessor(),
            validator=Validator(),
        )
        batch = await service.start_batch([plan], "write-failure")
        result = (await service.wait(batch))[0]
        assert result.state == JobState.FAILED and result.error_code == "STORE_WRITE_FAILED"
        assert result.output_path and plan.final_path.read_bytes() == b"isolated test output"
        assert store.get_attempt(result.attempt_id) == result
