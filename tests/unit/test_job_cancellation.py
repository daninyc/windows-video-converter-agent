import asyncio
from types import SimpleNamespace

import pytest

from media_converter.config import AppPaths
from media_converter.jobs.job_service import JobService
from media_converter.jobs.models import JobState
from media_converter.media.toolchain import inspect_toolchain
from media_converter.storage.local_store import LocalStore
from tests.unit.test_batch_runner import FakeProcessor
from tests.unit.test_conversion_planner import make_plan

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("whole_batch", [False, True])
async def test_cancel_wins_over_zero_exit_and_limits_scope(whole_batch, fixture_root, tmp_path):
    first = make_plan(fixture_root, tmp_path, relative="media/无音频.mp4")
    second = make_plan(fixture_root, tmp_path, relative="media/超短.mp4")

    class Processor(FakeProcessor):
        async def run(self, plan, cancel, callback, **kwargs):
            self.calls.append(plan.attempt_id)
            if plan == first:
                await cancel.wait()
            plan.temporary_path.write_bytes(b"fake output")
            return SimpleNamespace(exit_code=0, cancelled=False)

    class Validator:
        async def validate(self, plan):
            return {"test_double": True}

    with LocalStore(tmp_path / "state.sqlite3") as store:
        processor = Processor()
        service = JobService(
            store,
            inspect_toolchain(AppPaths.from_argument(tmp_path / "data")),
            processor=processor,
            validator=Validator(),
        )
        batch = await service.start_batch([first, second], "command")
        while not processor.calls:
            await asyncio.sleep(0.005)
        if whole_batch:
            await service.cancel_batch(batch)
        else:
            await service.cancel_current(batch)
        results = await service.wait(batch)
        assert results[0].state == JobState.CANCELLED
        assert results[1].state == (JobState.CANCELLED if whole_batch else JobState.SUCCEEDED)
        assert len(processor.calls) == (1 if whole_batch else 2)
        assert not first.final_path.exists() and not first.temporary_path.parent.exists()


async def test_cancel_during_validation_never_publishes(fixture_root, tmp_path):
    plan = make_plan(fixture_root, tmp_path, relative="media/无音频.mp4")
    reached = asyncio.Event()

    class Validator:
        async def validate(self, plan):
            reached.set()
            await asyncio.sleep(30)

    with LocalStore(tmp_path / "state.sqlite3") as store:
        service = JobService(
            store,
            inspect_toolchain(AppPaths.from_argument(tmp_path / "data")),
            processor=FakeProcessor(),
            validator=Validator(),
        )
        batch = await service.start_batch([plan], "command")
        await reached.wait()
        await service.cancel_current(batch)
        assert (await service.wait(batch))[0].state == JobState.CANCELLED
        assert not plan.final_path.exists()
