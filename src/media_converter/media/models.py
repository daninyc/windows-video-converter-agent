import hashlib
import json
from pathlib import Path, PureWindowsPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from media_converter.common.context import new_id


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FrameRate(FrozenModel):
    numerator: int = Field(gt=0)
    denominator: int = Field(gt=0)


class FileFingerprint(FrozenModel):
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    file_identity: str

    @classmethod
    def from_path(cls, path: Path) -> Self:
        stat = path.stat()
        return cls(
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            file_identity=f"{stat.st_dev}:{stat.st_ino}",
        )


class ImportRoot(FrozenModel):
    root_id: str = Field(default_factory=new_id)
    resolved_path: Path
    display_group: str
    recursive: bool = False
    kind: Literal["directory", "single"] = "directory"


class StreamInfo(FrozenModel):
    stream_index: int = Field(ge=0)
    kind: Literal["video", "audio", "subtitle", "data", "attachment", "unknown"]
    codec: str | None = None
    language: str | None = None
    disposition: tuple[str, ...] = ()
    channels: int | None = Field(default=None, gt=0)
    sample_rate_hz: int | None = Field(default=None, gt=0)
    subtitle_type: str | None = None
    attached_picture: bool = False


class MediaAsset(FrozenModel):
    asset_id: str = Field(default_factory=new_id)
    root_id: str
    relative_path: str
    resolved_path: Path
    fingerprint: FileFingerprint
    container: str | None = None
    duration_us: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    rotation_deg: int | None = None
    bitrate_bps: int | None = Field(default=None, ge=0)
    frame_rate: FrameRate | None = None
    variable_frame_rate: bool | None = None
    color_info: tuple[tuple[str, str], ...] = ()
    streams: tuple[StreamInfo, ...] = ()
    probe_status: Literal["pending", "probing", "succeeded", "failed"] = "pending"
    probe_error_code: str | None = None
    average_frame_rate: FrameRate | None = None

    @model_validator(mode="after")
    def validate_relative_path(self) -> Self:
        path = PureWindowsPath(self.relative_path)
        if path.is_absolute() or path.drive or ".." in path.parts:
            raise ValueError("relative_path must stay within its import root")
        indices = [s.stream_index for s in self.streams]
        if len(indices) != len(set(indices)):
            raise ValueError("stream indices must be unique")
        return self


class Resolution(FrozenModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ConversionSettings(FrozenModel):
    settings_version: int = Field(default=1, ge=1)
    container: Literal["mp4", "mkv", "webm"] = "mp4"
    video_encoder: str = "libx264"
    quality_mode: Literal["crf", "bitrate"] = "crf"
    quality_value: int | None = Field(default=23, ge=0)
    video_bitrate_bps: int | None = Field(default=None, gt=0)
    resolution: Resolution | None = None
    frame_rate: FrameRate | None = None
    audio_encoder: str = "aac"
    audio_bitrate_bps: int | None = Field(default=None, gt=0)
    output_mode: Literal["unified", "beside_source"] = "unified"
    output_dir: Path | None = None
    preserve_hierarchy: bool = False

    @model_validator(mode="after")
    def validate_quality(self) -> Self:
        if self.quality_mode == "crf":
            if self.quality_value is None or self.video_bitrate_bps is not None:
                raise ValueError("CRF and fixed bitrate are mutually exclusive")
        elif self.quality_value is not None or self.video_bitrate_bps is None:
            raise ValueError("bitrate mode requires bitrate and no CRF")
        return self


class StreamMapping(FrozenModel):
    source_index: int = Field(ge=0)
    kind: Literal["video", "audio", "subtitle"]
    action: Literal["copy", "transcode"]
    encoder: str | None = None


class LossItem(FrozenModel):
    stream_index: int = Field(ge=0)
    kind: str
    reason: str


class ConversionPlan(FrozenModel):
    plan_id: str = Field(default_factory=new_id)
    plan_hash: str = ""
    asset_id: str
    source_path: Path
    source_fingerprint: FileFingerprint
    settings_snapshot: ConversionSettings
    stream_mapping: tuple[StreamMapping, ...]
    loss_items: tuple[LossItem, ...] = ()
    consent_plan_hash: str | None = None
    ffmpeg_args: tuple[str, ...]
    temporary_path: Path
    final_path: Path
    attempt_id: str = Field(default_factory=new_id)
    source_asset: MediaAsset | None = None
    output_root: Path | None = None

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        payload = self.model_dump(
            mode="json", exclude={"plan_id", "plan_hash", "consent_plan_hash"}
        )
        digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        if self.plan_hash and self.plan_hash != digest:
            raise ValueError("plan content does not match plan_hash")
        if self.consent_plan_hash is not None and self.consent_plan_hash != digest:
            raise ValueError("consent belongs to a different plan")
        if self.final_path == self.source_path or self.temporary_path == self.source_path:
            raise ValueError("output must not replace source")
        object.__setattr__(self, "plan_hash", digest)
        return self

    @property
    def consent_satisfied(self) -> bool:
        return not self.loss_items or self.consent_plan_hash == self.plan_hash

    def confirm(self, expected_hash: str) -> Self:
        return type(self).model_validate({**self.model_dump(), "consent_plan_hash": expected_hash})
