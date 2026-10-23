import asyncio
import errno
from dataclasses import dataclass
from datetime import UTC, datetime

from media_converter.common.context import CallContext, new_id
from media_converter.common.errors import AppError, ErrorCode
from media_converter.common.logging import JsonlLogger
from media_converter.jobs.ffmpeg_process import FFmpegProcess
from media_converter.jobs.models import TERMINAL_STATES, JobAttempt, JobState
from media_converter.jobs.output_commit import OutputLease
from media_converter.jobs.output_validator import OutputValidator
from media_converter.jobs.state_machine import transition
from media_converter.media.models import ConversionPlan, FileFingerprint
from media_converter.media.planner import ConversionPlanner
from media_converter.media.probe import ProbeService


class JobCancelled(Exception):
    pass


@dataclass(frozen=True)
class JobEvent:
    kind: str
    batch_id: str
    attempt: JobAttempt | None
    counts: dict
    progress: object = None


class JobService:
    """All methods run on one asyncio loop; SQLite owns its own serial writer."""

    def __init__(
        self, store, capabilities, on_event=None, *, processor=None, validator=None, logger=None
    ):
        self.store = store
        self.capabilities = capabilities
        self.logger = logger or JsonlLogger()
        self.processor = processor or FFmpegProcess(capabilities, self.logger)
        self.validator = validator or OutputValidator(capabilities)
        self.on_event = on_event or (lambda event: None)
        self._start_lock = asyncio.Lock()
        self._tasks = {}
        self._attempts = {}
        self._active_batch = None
        self._cancel_all = set()
        self._current_cancel = {}
        self._current_attempt = {}
        self._committing = set()
        self.validations = {}

    def counts(self, batch_id):
        attempts = [attempt for attempt in self._attempts.values() if attempt.batch_id == batch_id]
        return {
            "total": len(attempts),
            "completed": sum(a.state in TERMINAL_STATES for a in attempts),
            "succeeded": sum(a.state == JobState.SUCCEEDED for a in attempts),
            "failed": sum(a.state == JobState.FAILED for a in attempts),
            "cancelled": sum(a.state == JobState.CANCELLED for a in attempts),
        }

    def _emit(self, kind, batch_id, attempt=None, progress=None):
        self.on_event(JobEvent(kind, batch_id, attempt, self.counts(batch_id), progress))

    async def start_batch(self, plans, batch_command_id, *, retry_job_id=None):
        plans = tuple(ConversionPlan.model_validate(plan.model_dump()) for plan in plans)
        if not plans or len({plan.attempt_id for plan in plans}) != len(plans):
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        async with self._start_lock:
            existing = await asyncio.to_thread(self.store.get_batch_command, batch_command_id)
            if existing:
                if existing["plan_ids"] != [plan.plan_id for plan in plans]:
                    raise AppError(ErrorCode.INVALID_ARGUMENT)
                return existing["batch_id"]
            if self._active_batch is not None:
                raise AppError(ErrorCode.INVALID_STATE)
            batch_id = new_id()
            attempts = tuple(
                JobAttempt(
                    job_id=retry_job_id or new_id(),
                    attempt_id=plan.attempt_id,
                    batch_id=batch_id,
                    asset_id=plan.asset_id,
                    plan_id=plan.plan_id,
                )
                for plan in plans
            )
            await asyncio.to_thread(
                self.store.register_batch, batch_command_id, batch_id, plans, attempts
            )
            self._attempts.update((attempt.attempt_id, attempt) for attempt in attempts)
            self._active_batch = batch_id
            self._emit("batch_started", batch_id)
            for attempt in attempts:
                self._emit("state", batch_id, attempt)
            self._tasks[batch_id] = asyncio.create_task(self._run_batch(batch_id, plans))
            return batch_id

    async def wait(self, batch_id):
        if batch_id in self._tasks:
            await asyncio.shield(self._tasks[batch_id])
            return tuple(
                attempt for attempt in self._attempts.values() if attempt.batch_id == batch_id
            )
        return tuple(
            attempt
            for attempt in await asyncio.to_thread(self.store.list_attempts)
            if attempt.batch_id == batch_id
        )

    async def _state(self, attempt_id, state, **updates):
        old = self._attempts[attempt_id]
        attempt = transition(old, state, **updates)
        try:
            await asyncio.to_thread(self.store.save_attempt, attempt)
        except Exception as error:
            raise AppError(ErrorCode.STORE_WRITE_FAILED) from error
        self._attempts[attempt_id] = attempt
        self.logger.event(
            "conversion.state",
            CallContext(trace_id=attempt.batch_id),
            attempt_id=attempt.attempt_id,
            state=attempt.state,
            error_code=attempt.error_code,
        )
        self._emit("state", attempt.batch_id, attempt)
        return attempt

    def _progress(self, attempt_id, progress):
        current = self._attempts[attempt_id]
        if current.state != JobState.RUNNING:
            return
        current = JobAttempt.model_validate(
            {**current.model_dump(), "progress_us": progress.processed_us}
        )
        self._attempts[attempt_id] = current
        self._emit("progress", current.batch_id, current, progress)

    async def _run_batch(self, batch_id, plans):
        try:
            for plan in plans:
                if batch_id in self._cancel_all:
                    await self._state(plan.attempt_id, JobState.CANCELLED)
                    continue
                cancel = asyncio.Event()
                self._current_cancel[batch_id] = cancel
                self._current_attempt[batch_id] = plan.attempt_id
                await self._run_one(plan, cancel)
        except asyncio.CancelledError:
            self._cancel_all.add(batch_id)
            for plan in plans:
                attempt = self._attempts[plan.attempt_id]
                if attempt.state not in TERMINAL_STATES:
                    await self._cancel_attempt(plan.attempt_id)
            raise
        finally:
            self._current_cancel.pop(batch_id, None)
            self._current_attempt.pop(batch_id, None)
            self._active_batch = None
            self._emit("batch_finished", batch_id)

    async def _cancel_attempt(self, attempt_id):
        attempt = self._attempts[attempt_id]
        if attempt.state in TERMINAL_STATES:
            return
        if attempt.state in (JobState.RUNNING, JobState.VERIFYING):
            await self._state(attempt_id, JobState.CANCELLING)
        await self._state(attempt_id, JobState.CANCELLED)

    async def _validate_cancellable(self, plan, cancel):
        checking = asyncio.create_task(self.validator.validate(plan))
        cancelling = asyncio.create_task(cancel.wait())
        try:
            await asyncio.wait([checking, cancelling], return_when=asyncio.FIRST_COMPLETED)
            if cancel.is_set():
                raise JobCancelled()
            return await checking
        finally:
            checking.cancel()
            cancelling.cancel()
            await asyncio.gather(checking, cancelling, return_exceptions=True)

    @staticmethod
    def _check_source(plan):
        try:
            current = FileFingerprint.from_path(plan.source_path)
        except (FileNotFoundError, NotADirectoryError) as error:
            raise AppError(ErrorCode.FILE_CHANGED) from error
        if current != plan.source_fingerprint:
            raise AppError(ErrorCode.FILE_CHANGED)

    async def _run_one(self, plan, cancel):
        lease = OutputLease(plan)
        try:
            await self._state(plan.attempt_id, JobState.PREPARING)
            if cancel.is_set():
                raise JobCancelled()
            self._check_source(plan)
            if not plan.consent_satisfied:
                await self._state(plan.attempt_id, JobState.NEEDS_CONFIRMATION)
                raise AppError(ErrorCode.CONSENT_REQUIRED)
            await self._state(plan.attempt_id, JobState.READY)
            await asyncio.to_thread(lease.acquire)
            if cancel.is_set():
                raise JobCancelled()
            await self._state(plan.attempt_id, JobState.RUNNING)
            if cancel.is_set():
                raise JobCancelled()
            result = await self.processor.run(
                plan,
                cancel,
                lambda progress: self._progress(plan.attempt_id, progress),
                context=CallContext(trace_id=self._attempts[plan.attempt_id].batch_id),
            )
            if cancel.is_set() or result.cancelled:
                raise JobCancelled()
            if result.exit_code:
                raise AppError(ErrorCode(result.error_code or ErrorCode.PROCESS_FAILED))
            await self._state(plan.attempt_id, JobState.VERIFYING, exit_code=result.exit_code)
            checked = await self._validate_cancellable(plan, cancel)
            self._check_source(plan)
            if cancel.is_set():
                raise JobCancelled()
            # No await between final cancellation check and no-replace publication.
            self._committing.add(plan.attempt_id)
            published = lease.commit()
            self.validations[plan.attempt_id] = checked
            await self._state(plan.attempt_id, JobState.SUCCEEDED, output_path=str(published))
        except JobCancelled:
            await self._cancel_attempt(plan.attempt_id)
        except asyncio.CancelledError:
            cancel.set()
            await self._cancel_attempt(plan.attempt_id)
            raise
        except Exception as error:
            code = (
                error.info.code
                if isinstance(error, AppError)
                else (
                    ErrorCode.DISK_FULL
                    if isinstance(error, OSError) and error.errno == errno.ENOSPC
                    else ErrorCode.ACCESS_DENIED
                    if isinstance(error, PermissionError)
                    else ErrorCode.PROCESS_FAILED
                )
            )
            try:
                if cancel.is_set():
                    await self._cancel_attempt(plan.attempt_id)
                else:
                    await self._state(
                        plan.attempt_id,
                        JobState.FAILED,
                        error_code=code,
                        output_path=str(lease.published_path) if lease.published_path else None,
                    )
            except AppError as persistence_error:
                if persistence_error.info.code != ErrorCode.STORE_WRITE_FAILED:
                    raise
                current = self._attempts[plan.attempt_id]
                failed = JobAttempt.model_validate(
                    {
                        **current.model_dump(),
                        "state": JobState.CANCELLED if cancel.is_set() else JobState.FAILED,
                        "error_code": ErrorCode.STORE_WRITE_FAILED,
                        "finished_at": datetime.now(UTC),
                        "output_path": str(lease.published_path) if lease.published_path else None,
                    }
                )
                self._attempts[plan.attempt_id] = failed
                self.logger.event(
                    "conversion.state_unpersisted",
                    CallContext(trace_id=failed.batch_id),
                    attempt_id=failed.attempt_id,
                    error_code=failed.error_code,
                )
                self._emit("state", failed.batch_id, failed)
        finally:
            self._committing.discard(plan.attempt_id)
            try:
                await asyncio.to_thread(lease.cleanup)
            except (OSError, AppError):
                self.logger.event(
                    "conversion.cleanup_failed",
                    CallContext(trace_id=self._attempts[plan.attempt_id].batch_id),
                    attempt_id=plan.attempt_id,
                    error_code=ErrorCode.ACCESS_DENIED,
                )

    async def cancel_current(self, batch_id):
        cancel = self._current_cancel.get(batch_id)
        if self._current_attempt.get(batch_id) in self._committing:
            return False
        if cancel is not None and batch_id == self._active_batch:
            cancel.set()
            return True
        return False

    async def shutdown(self):
        if self._active_batch:
            await self.cancel_batch(self._active_batch)
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def cancel_batch(self, batch_id):
        if batch_id != self._active_batch:
            return False
        self._cancel_all.add(batch_id)
        await self.cancel_current(batch_id)
        return True

    async def prepare_retry(self, attempt_id):
        old = await asyncio.to_thread(self.store.get_attempt, attempt_id)
        if old is None or old.state not in {
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.INTERRUPTED,
        }:
            raise AppError(ErrorCode.INVALID_STATE)
        previous = await asyncio.to_thread(self.store.get_plan, old.plan_id)
        if previous is None or previous.source_asset is None:
            raise AppError(ErrorCode.INVALID_STATE)
        source = await ProbeService(self.capabilities.ffprobe.path, self.store).probe(
            previous.source_asset
        )
        if source.probe_status != "succeeded":
            raise AppError(ErrorCode(source.probe_error_code))
        root = await asyncio.to_thread(self.store.get_import_root, source.root_id)
        if root is None:
            raise AppError(ErrorCode.INVALID_STATE)
        return await asyncio.to_thread(
            ConversionPlanner(self.capabilities).plan_one, previous.settings_snapshot, source, root
        )

    async def retry(self, attempt_id, confirmed_plan):
        existing = await asyncio.to_thread(self.store.get_batch_command, "retry:" + attempt_id)
        if existing:
            return existing["batch_id"]
        old = await asyncio.to_thread(self.store.get_attempt, attempt_id)
        if old is None or old.state not in {
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.INTERRUPTED,
        }:
            raise AppError(ErrorCode.INVALID_STATE)
        previous = await asyncio.to_thread(self.store.get_plan, old.plan_id)
        if (
            previous is None
            or confirmed_plan.asset_id != old.asset_id
            or confirmed_plan.settings_snapshot != previous.settings_snapshot
        ):
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        return await self.start_batch(
            [confirmed_plan], "retry:" + attempt_id, retry_job_id=old.job_id
        )
