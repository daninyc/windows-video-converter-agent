import pytest
from pydantic import ValidationError

from media_converter.common.errors import AppError
from media_converter.jobs.models import TERMINAL_STATES, JobAttempt, JobState
from media_converter.jobs.state_machine import retry, transition
from media_converter.media.models import (
    ConversionPlan,
    ConversionSettings,
    FileFingerprint,
    FrameRate,
    LossItem,
    MediaAsset,
    StreamInfo,
    StreamMapping,
)

pytestmark = pytest.mark.unit


def make_asset(tmp_path):
    source = tmp_path / "测试 video.mp4"
    source.write_bytes(b"synthetic")
    return MediaAsset(
        root_id="root",
        relative_path=source.name,
        resolved_path=source,
        fingerprint=FileFingerprint.from_path(source),
    )


def test_units_unknown_vfr_and_immutable_roundtrip(tmp_path):
    asset = make_asset(tmp_path)
    assert asset.duration_us is None and asset.frame_rate is None
    vfr = asset.model_copy(
        update={
            "variable_frame_rate": True,
            "frame_rate": FrameRate(numerator=30000, denominator=1001),
        }
    )
    assert MediaAsset.model_validate_json(vfr.model_dump_json()) == vfr
    settings = ConversionSettings()
    with pytest.raises(ValidationError):
        settings.settings_version = 2
    with pytest.raises(ValidationError):
        ConversionSettings(video_bitrate_bps=1_000_000)
    with pytest.raises(ValidationError):
        FrameRate(numerator=30, denominator=0)
    stream = StreamInfo(stream_index=1, kind="audio", channels=2, sample_rate_hz=48000)
    assert stream.sample_rate_hz == 48000


def test_plan_hash_streams_and_consent_roundtrip(tmp_path):
    asset = make_asset(tmp_path)
    plan = ConversionPlan(
        asset_id=asset.asset_id,
        source_path=asset.resolved_path,
        source_fingerprint=asset.fingerprint,
        settings_snapshot=ConversionSettings(),
        stream_mapping=(StreamMapping(source_index=0, kind="video", action="transcode"),),
        loss_items=(LossItem(stream_index=2, kind="subtitle", reason="incompatible"),),
        ffmpeg_args=("-i", str(asset.resolved_path)),
        temporary_path=tmp_path / "out.partial.mp4",
        final_path=tmp_path / "out.mp4",
    )
    assert not plan.consent_satisfied
    confirmed = plan.confirm(plan.plan_hash)
    assert confirmed.consent_satisfied
    assert ConversionPlan.model_validate_json(confirmed.model_dump_json()) == confirmed
    with pytest.raises(ValidationError):
        ConversionPlan.model_validate(
            {**confirmed.model_dump(), "final_path": tmp_path / "other.mp4"}
        )


@pytest.mark.parametrize("terminal", list(TERMINAL_STATES))
def test_terminal_late_callbacks_and_duplicate_events(terminal):
    attempt = JobAttempt(batch_id="batch", asset_id="asset", plan_id="plan", state=terminal)
    assert transition(attempt, terminal) is attempt
    target = JobState.RUNNING if terminal == JobState.SUCCEEDED else JobState.SUCCEEDED
    with pytest.raises(AppError):
        transition(attempt, target)
    if terminal != JobState.SUCCEEDED:
        retried = retry(attempt)
        assert retried.attempt_id != attempt.attempt_id and retried.job_id == attempt.job_id
        assert attempt.state == terminal and retried.state == JobState.QUEUED


def test_normal_cancel_and_illegal_transition():
    attempt = JobAttempt(batch_id="b", asset_id="a", plan_id="p")
    with pytest.raises(AppError):
        transition(attempt, JobState.SUCCEEDED)
    for state in (
        JobState.PREPARING,
        JobState.READY,
        JobState.RUNNING,
        JobState.CANCELLING,
        JobState.CANCELLED,
    ):
        attempt = transition(attempt, state)
    assert attempt.started_at and attempt.finished_at
    with pytest.raises(AppError):
        transition(attempt, JobState.SUCCEEDED)
