from datetime import datetime
from enum import StrEnum

from pydantic import Field

from media_converter.common.context import new_id
from media_converter.media.models import FrozenModel


class JobState(StrEnum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    CANCELLING = "CANCELLING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


TERMINAL_STATES = frozenset(
    {
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.INTERRUPTED,
    }
)


class BatchCommand(FrozenModel):
    batch_id: str = Field(default_factory=new_id)
    batch_command_id: str = Field(default_factory=new_id)
    plan_ids: tuple[str, ...]


class JobAttempt(FrozenModel):
    job_id: str = Field(default_factory=new_id)
    attempt_id: str = Field(default_factory=new_id)
    batch_id: str
    asset_id: str
    plan_id: str
    state: JobState = JobState.QUEUED
    progress_us: int | None = Field(default=None, ge=0)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error_code: str | None = None
    output_path: str | None = None
