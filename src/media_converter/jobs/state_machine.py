from datetime import UTC, datetime

from media_converter.common.context import new_id
from media_converter.common.errors import AppError, ErrorCode
from media_converter.jobs.models import TERMINAL_STATES, JobAttempt, JobState

_NEXT = {
    JobState.QUEUED: {JobState.PREPARING, JobState.CANCELLED, JobState.FAILED},
    JobState.PREPARING: {
        JobState.NEEDS_CONFIRMATION,
        JobState.READY,
        JobState.CANCELLED,
        JobState.FAILED,
    },
    JobState.NEEDS_CONFIRMATION: {JobState.READY, JobState.CANCELLED, JobState.FAILED},
    JobState.READY: {JobState.RUNNING, JobState.CANCELLED, JobState.FAILED},
    JobState.RUNNING: {JobState.VERIFYING, JobState.CANCELLING, JobState.FAILED},
    JobState.VERIFYING: {JobState.SUCCEEDED, JobState.CANCELLING, JobState.FAILED},
    JobState.CANCELLING: {JobState.CANCELLED},
}


def transition(attempt: JobAttempt, target: JobState, **updates) -> JobAttempt:
    target = JobState(target)
    if target == attempt.state:
        return attempt
    if attempt.state in TERMINAL_STATES:
        raise AppError(ErrorCode.INVALID_STATE)
    if target != JobState.INTERRUPTED and target not in _NEXT[attempt.state]:
        raise AppError(ErrorCode.INVALID_STATE)
    if any(
        key in updates
        for key in ("attempt_id", "job_id", "batch_id", "asset_id", "plan_id", "state")
    ):
        raise AppError(ErrorCode.INVALID_ARGUMENT)
    if target == JobState.RUNNING:
        updates["started_at"] = datetime.now(UTC)
    if target in TERMINAL_STATES:
        updates["finished_at"] = datetime.now(UTC)
    return JobAttempt.model_validate({**attempt.model_dump(), **updates, "state": target})


def retry(attempt: JobAttempt, *, plan_id: str | None = None) -> JobAttempt:
    if attempt.state not in {JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED}:
        raise AppError(ErrorCode.INVALID_STATE)
    return JobAttempt(
        job_id=attempt.job_id,
        attempt_id=new_id(),
        batch_id=attempt.batch_id,
        asset_id=attempt.asset_id,
        plan_id=plan_id or attempt.plan_id,
    )
